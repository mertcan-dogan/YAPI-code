"""CR-007-B — Agentic tool-use loop (orchestration).

Mirrors the existing services/ai.py vs api/ai.py split: this module orchestrates
the Anthropic tool-use loop; the read-only data lives in services/agent_tools.py.

Governing principle (§1.2): the model never computes numbers — it only calls the
fixed, read-only tools (which compute via SQL) and narrates the results. There is
no raw-SQL tool, and ``company_id`` is injected here from the authenticated user,
never taken from tool input.
"""
import calendar
import functools
import inspect
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.constants import COST_CATEGORIES
from app.services import agent_actions as actions
from app.services import agent_tools as tools
from app.services import ai as ai_service
from app.utils.format import format_date_tr, format_number_tr

logger = logging.getLogger("yapi.agent")

# Hard caps (§3.2). Token budget / timeout come from config (CR-007-E).
MAX_ITERATIONS = 6

DEGRADED_MESSAGE = "Yapay zeka şu an kullanılamıyor. Lütfen birazdan tekrar deneyin."

# §3.3 — keep verbatim.
SYSTEM_PROMPT = (
    "Sen bir Türk inşaat şirketinin AI finansal analiz ajanısın. Görevin: kullanıcının "
    "sorusunu anlamak, gereken verileri ARAÇLARI kullanarak çekmek, ve net bir Türkçe "
    "analiz sunmak.\n"
    "KESİN KURALLAR:\n"
    "1. Hiçbir sayıyı kendin hesaplama. Her rakam, toplam, yüzde ve ortalama yalnızca "
    "araç sonuçlarından gelmeli. Araç çağırmadan sayısal iddiada bulunma.\n"
    "2. Yanıtını yalnızca araçlardan dönen verilere dayandır. Veri yoksa \"Bu konuda "
    "veri bulunamadı\" de — tahmin etme.\n"
    "3. Karmaşık soruları adımlara böl: önce ilgili veriyi çek, sonra gerekirse "
    "karşılaştırma için ek veri çek, sonra yorumla.\n"
    "4. GRAFİK KURALI: Yanıtın aylık/zaman serisi bir kırılım (by_month) VEYA çok "
    "noktalı bir kategori/proje kırılımı içeriyorsa, kullanıcı istemese bile create_chart "
    "aracını MUTLAKA çağır — sormayı bekleme. Özellikle tedarikçi harcaması "
    "(get_vendor_spend) yanıtlarında DAİMA bir çizgi grafik üret: x ekseninde aylar, "
    "her cost_category için bir çizgi ve ayrıca bir toplam (Toplam) çizgisi. Grafik verisi "
    "yalnızca daha önce çektiğin araç sonuçlarındaki sayılardan gelmeli — veri icat etme. "
    "Tek bir skaler yanıtta (örn. 'kaç projemiz var') grafik üretme.\n"
    "5. Her önemli rakamın kaynağını belirt — ilgili kayıtların kimlikleri araç "
    "sonuçlarında \"deep_link\" olarak gelir.\n"
    "6. Yanıt Türkçe, sade ve eyleme yönelik olsun. Önemli rakamları **kalın** yaz. "
    "Para birimini Türkçe formatta göster (₺, %, M).\n"
    "7. Eğer bir tedarikçi adı birden fazla varyantla eşleşirse, bunu kullanıcıya açıkça "
    "belirt."
)


# --------------------------------------------------------------------------- #
# Server-resolved relative date windows (CR-011-A §1.2 / §0.2.5)
# The model NEVER does date math: for a relative period it passes a named
# `relative_window`; the server resolves it to literal ISO start/end from the
# real `today` before the tool runs. Explicit dates from the user are still
# copied verbatim by the model. Replaces the CR-007-K "BUGÜN: model-computes-it"
# stopgap (A1).
# --------------------------------------------------------------------------- #
RELATIVE_WINDOWS = (
    "bu_ay", "gecen_ay", "son_3_ay", "son_6_ay", "son_12_ay",
    "bu_yil", "gecen_yil", "bu_ceyrek", "gecen_ceyrek",
)


def _add_months(d: date, months: int) -> date:
    """Shift a date by N calendar months, clamping the day to the target month."""
    idx = d.month - 1 + months
    y = d.year + idx // 12
    m = idx % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def resolve_window(name: str, today: date) -> tuple[date | None, date | None]:
    """Resolve a named relative window to literal (date_from, date_to) on the
    server (§1.2). Rolling windows ("son N ay") count back from today; calendar
    windows ("bu/geçen ay·yıl·çeyrek") align to month/year/quarter boundaries.
    Unknown names resolve to (None, None) so the tool keeps any explicit dates."""
    if name == "bu_ay":
        return date(today.year, today.month, 1), today
    if name == "gecen_ay":
        last_prev = date(today.year, today.month, 1) - timedelta(days=1)
        return date(last_prev.year, last_prev.month, 1), last_prev
    if name == "son_3_ay":
        return _add_months(today, -3), today
    if name == "son_6_ay":
        return _add_months(today, -6), today
    if name == "son_12_ay":
        return _add_months(today, -12), today
    if name == "bu_yil":
        return date(today.year, 1, 1), today
    if name == "gecen_yil":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if name == "bu_ceyrek":
        q = (today.month - 1) // 3
        return date(today.year, q * 3 + 1, 1), today
    if name == "gecen_ceyrek":
        start_this_q = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
        last_prev_q = start_this_q - timedelta(days=1)
        pq = (last_prev_q.month - 1) // 3
        return date(last_prev_q.year, pq * 3 + 1, 1), last_prev_q
    return None, None


# CR-011 follow-up (Item 2) — named relative due-dates for reminders, resolved on
# the SERVER (§0.2.5 — the model never computes dates).
RELATIVE_DUE = ("bugun", "yarin", "gelecek_hafta", "iki_hafta", "ay_sonu", "gelecek_ay")


def resolve_due(name: str, today: date) -> date | None:
    """Resolve a named relative reminder due-date to a literal date. Unknown → None."""
    if name == "bugun":
        return today
    if name == "yarin":
        return today + timedelta(days=1)
    if name == "gelecek_hafta":
        return today + timedelta(days=7)
    if name == "iki_hafta":
        return today + timedelta(days=14)
    if name == "ay_sonu":
        return _add_months(date(today.year, today.month, 1), 1) - timedelta(days=1)
    if name == "gelecek_ay":
        return _add_months(today, 1)
    return None


def _date_guidance(today: date) -> str:
    """System-prompt date rules (§0.2.5): today's date is grounding context only —
    the model must NOT do date math. Relative periods go through the tools'
    `relative_window` parameter, which the server resolves to literal ISO dates."""
    return (
        f"\n\nBUGÜN: {today:%Y-%m-%d} (yalnızca bağlam; tarih HESABI YAPMA). Göreli "
        "bir dönem için (son 6 ay, geçen ay, bu yıl, son çeyrek, geçen yıl...) "
        "araçların `relative_window` parametresini kullan — sunucu bunu birebir ISO "
        "tarihlerine çevirir. date_from/date_to'yu yalnızca kullanıcı AÇIK bir tarih "
        "verdiğinde, o tarihi kopyalayarak ver. Tarihleri kendin hesaplama."
    )


# --------------------------------------------------------------------------- #
# Tool registry: name -> (callable, allowed-param whitelist)
# The whitelist also blocks a model-supplied company_id (§1.2 #4).
# --------------------------------------------------------------------------- #
_DATE_PARAMS = {"date_from", "date_to"}

TOOL_REGISTRY = {
    "list_projects": (tools.list_projects, {"status"}),
    "get_project_financials": (tools.get_project_financials, {"project_id"}),
    "query_cost_entries": (tools.query_cost_entries, {
        "project_id", "date_from", "date_to", "cost_category", "supplier_name",
        "subcontractor_id", "payment_status", "entry_type", "group_by",
    }),
    "query_client_invoices": (tools.query_client_invoices, {
        "project_id", "date_from", "date_to", "payment_status", "invoice_type", "group_by",
    }),
    "query_subcontractors": (tools.query_subcontractors, {"project_id", "name"}),
    "get_vendor_spend": (tools.get_vendor_spend, {"vendor_name", "date_from", "date_to"}),
    "compare_vendors": (tools.compare_vendors, {"date_from", "date_to", "top_n", "cost_category"}),
    "get_cashflow": (tools.get_cashflow, {"project_id", "window_days"}),
    "get_overdue_payments": (tools.get_overdue_payments, {"project_id"}),
    # CR-011-B — new read-only tools.
    "get_equipment_utilisation": (tools.get_equipment_utilisation, {"project_id", "ownership_type"}),
    "get_budget_variance": (tools.get_budget_variance, {"project_id", "cost_category"}),
    "get_retention_summary": (tools.get_retention_summary, {"project_id"}),
    "get_assurance_findings": (tools.get_assurance_findings, {"project_id", "severity"}),
    # CR-035 — read-only Report Studio catalog (valid dimension/metric ids the
    # agent uses to build a report/dashboard spec before proposing one).
    "studio_catalog": (tools.studio_catalog, set()),
}

# CR-011-C — ACTION tools (propose-only). Kept in a SEPARATE registry so the
# read-only guarantee on TOOL_REGISTRY stays intact and the executor routes
# actions through the approvals lifecycle (never a direct mutation, §0.2.1).
ACTION_TOOL_REGISTRY = {
    "propose_reminder": (actions.propose_reminder, {"title", "note", "due_date", "project_id"}),
    "propose_flag_invoice": (actions.propose_flag_invoice,
                             {"target_kind", "target_id", "reason", "project_id"}),
    "propose_followup_task": (actions.propose_followup_task, {"title", "note", "project_id"}),
    # CR-035/CR-039 — author a Report Studio report / dashboard. CR-039: these are
    # DRAFT tools — the spec/widget payload is validated against the catalog, then a
    # draft_* proposed-action is returned with NO ApprovalRequest and NO write. The
    # row is created only by the user's explicit OLUŞTUR click (POST /studio/...),
    # which strengthens the CR-011 never-writes invariant.
    "propose_report": (actions.propose_report,
                       {"title", "spec", "visibility", "labels", "project_id"}),
    "propose_dashboard": (actions.propose_dashboard,
                          {"title", "widgets", "date_range", "comparison", "filters",
                           "visibility", "labels", "project_id"}),
    # CR-044 — DRAFT a Skill (Beceri): same draft-only contract (validate the plan,
    # return a draft_skill, write NOTHING). The Skill is saved by the user's own
    # "Beceri olarak kaydet" click (POST /skills).
    "propose_skill": (actions.propose_skill,
                      {"name", "widgets", "format", "instruction", "date_range",
                       "visibility", "labels", "project_scope", "project_id"}),
}
ACTION_TOOL_NAMES = set(ACTION_TOOL_REGISTRY)


def build_tool_schemas() -> list[dict]:
    """Anthropic tool definitions — one per read-only tool plus create_chart.
    No input_schema contains a company_id field (§1.2 #4)."""
    group_by_cost = {"type": "string", "enum": ["month", "category", "supplier", "project"]}
    group_by_inv = {"type": "string", "enum": ["month", "type", "status", "project"]}
    date_s = {"type": "string", "description": "YYYY-MM-DD"}
    pid = {"type": "string", "description": "Proje UUID"}
    # CR-011-A §1.2 — relative period; the SERVER resolves it to literal ISO dates.
    # Use this instead of computing date_from/date_to yourself.
    rel_window = {
        "type": "string", "enum": list(RELATIVE_WINDOWS),
        "description": (
            "Göreli dönem (sunucu birebir ISO tarihlere çevirir). Açık tarih "
            "verilmediyse göreli dönemler için bunu kullan; tarihi kendin hesaplama."
        ),
    }
    # CR-035 — the CR-032 Spec shape the agent emits for propose_report and for each
    # data widget of propose_dashboard. metrics[] is required; metrics/dimensions/
    # filter-fields MUST be ids from studio_catalog (validate_spec rejects others).
    spec_obj = {
        "type": "object",
        "description": (
            "CR-032 Rapor Spec'i. metrics[] ZORUNLU. metrics, dimensions ve "
            "filtre alanları SADECE studio_catalog'daki kimliklerden olmalı "
            "('coming_soon' olanları kullanma). viz: line|area|bar|kpi|table — "
            "veri şekline uygun seç: zaman serisi (month/quarter/year) → line/area, "
            "kategori/vendor kırılımı → bar, tek değer/anlık → kpi. (Motor grafiği "
            "şekle göre otomatik seçer/eler; uygunsuz grafik koyma.)"
        ),
        "properties": {
            "metrics": {"type": "array", "items": {"type": "string"},
                        "description": "Katalog metrik kimlikleri (en az bir; ZORUNLU)."},
            "dimensions": {"type": "array", "items": {"type": "string"},
                           "description": "Katalog boyut kimlikleri (kırılım)."},
            "viz": {"type": "string", "enum": ["line", "area", "bar", "kpi", "table"]},
            "filters": {"type": "array", "items": {
                "type": "object", "properties": {
                    "field": {"type": "string", "description": "Katalog boyut kimliği"},
                    "op": {"type": "string", "enum": ["=", "!=", "in", "not_in"]},
                    "value": {},
                }, "required": ["field", "op", "value"]}},
            "date_range": {"type": "object",
                           "description": ("{preset} (örn. bu_yil, son_3_ay, tum_zamanlar) "
                                           "veya {from,to} ISO tarih. Proje ömrü/analizi için "
                                           "varsayılan tum_zamanlar (all_time).")},
            "sort": {"type": "object", "description": "{by: metrik/boyut kimliği, dir: asc|desc}"},
            "limit": {"type": "integer"},
            "basis": {"type": "object",
                      "description": "Opsiyonel {cost, currency, financing, vat} hesap bazı."},
        },
        "required": ["metrics"],
    }
    widget_obj = {
        "type": "object",
        "description": (
            "Pano widget'ı. Veri widget'ı (kpi/chart/table) bir 'spec' içermeli; "
            "'text' widget'ı 'content' içermeli. Her widget benzersiz bir 'id' ve "
            "bir 'layout' (x,y,w,h grid hücresi) almalı."
        ),
        "properties": {
            "id": {"type": "string", "description": "Pano içinde benzersiz"},
            "type": {"type": "string", "enum": ["kpi", "chart", "table", "text"]},
            "title": {"type": "string"},
            "layout": {"type": "object", "properties": {
                "x": {"type": "integer"}, "y": {"type": "integer"},
                "w": {"type": "integer"}, "h": {"type": "integer"},
            }, "required": ["x", "y", "w", "h"]},
            "spec": spec_obj,
            "content": {"type": "string", "description": "Yalnızca type='text' için"},
        },
        "required": ["id", "type", "title", "layout"],
    }

    return [
        {
            "name": "list_projects",
            "description": (
                "Şirketin tüm projelerinin portföy özetini döndürür (durum filtresi "
                "opsiyonel). Her kayıt: id, name, project_code, status ve revenue_model "
                "(gelir modeli: hakedis | kat_karsiligi | yap_sat | hasilat_paylasimi | "
                "maliyet_kar) içerir. Bir proje ADINI id'ye çözmek ve hangi gelir "
                "metriğinin doğru olduğunu seçmek için bunu kullan."
            ),
            "input_schema": {"type": "object", "properties": {
                "status": {"type": "string", "enum": ["active", "completed", "suspended", "cancelled"]},
            }},
        },
        {
            "name": "get_project_financials",
            "description": "Tek bir projenin tam hesaplanmış KPI özetini (marj, nakit, tahmini final) döndürür.",
            "input_schema": {"type": "object", "properties": {"project_id": pid}, "required": ["project_id"]},
        },
        {
            "name": "query_cost_entries",
            "description": "Maliyet (tedarikçi) kayıtlarını ve toplamlarını döndürür; group_by ile aylık/kategori/tedarikçi/proje kırılımı.",
            "input_schema": {"type": "object", "properties": {
                "project_id": pid, "date_from": date_s, "date_to": date_s,
                "relative_window": rel_window,
                "cost_category": {"type": "string"}, "supplier_name": {"type": "string"},
                "subcontractor_id": {"type": "string"}, "payment_status": {"type": "string"},
                "entry_type": {"type": "string"}, "group_by": group_by_cost,
            }},
        },
        {
            "name": "query_client_invoices",
            "description": "Hakediş / işveren faturalarını ve toplamlarını döndürür; group_by ile kırılım.",
            "input_schema": {"type": "object", "properties": {
                "project_id": pid, "date_from": date_s, "date_to": date_s,
                "relative_window": rel_window,
                "payment_status": {"type": "string"}, "invoice_type": {"type": "string"},
                "group_by": group_by_inv,
            }},
        },
        {
            "name": "query_subcontractors",
            "description": "Alt yüklenici sözleşmelerini (değer, ödenen, kesinti, kalan taahhüt) döndürür.",
            "input_schema": {"type": "object", "properties": {
                "project_id": pid, "name": {"type": "string"},
            }},
        },
        {
            "name": "get_vendor_spend",
            "description": "Bir tedarikçi ile TÜM portföyde yapılan harcamayı ay ve kategori bazında döndürür (çapraz proje).",
            "input_schema": {"type": "object", "properties": {
                "vendor_name": {"type": "string"}, "date_from": date_s, "date_to": date_s,
                "relative_window": rel_window,
            }, "required": ["vendor_name"]},
        },
        {
            "name": "compare_vendors",
            "description": "Bir dönemde tedarikçi başına toplam harcamayı sıralı (en yüksekten) döndürür.",
            "input_schema": {"type": "object", "properties": {
                "date_from": date_s, "date_to": date_s, "relative_window": rel_window,
                "top_n": {"type": "integer"}, "cost_category": {"type": "string"},
            }},
        },
        {
            "name": "get_cashflow",
            "description": "Aylık nakit giriş/çıkış serisi ve 30/60/90 gün nakit ihtiyacı projeksiyonu.",
            "input_schema": {"type": "object", "properties": {
                "project_id": pid, "window_days": {"type": "integer", "enum": [30, 60, 90]},
            }},
        },
        {
            "name": "get_overdue_payments",
            "description": "Vadesi geçmiş ödenecekler (tedarikçi) ve tahsilatlar (işveren).",
            "input_schema": {"type": "object", "properties": {"project_id": pid}},
        },
        {
            "name": "get_equipment_utilisation",
            "description": (
                "Ekipman kullanımı: makine bazında sahalama süresi, aktif/biten durumu, "
                "tahmini kira (kiralık için oran × süre) + yakıt/bakım ve sahiplik (owned/"
                "rented) bazında toplamlar."
            ),
            "input_schema": {"type": "object", "properties": {
                "project_id": pid,
                "ownership_type": {"type": "string", "enum": ["owned", "rented"]},
            }},
        },
        {
            "name": "get_budget_variance",
            "description": (
                "Bütçe-gerçekleşen sapması: proje/kategori bazında revize bütçe "
                "(orijinal + onaylı değişiklik) ile gerçekleşen (KDV dahil fiili maliyet) "
                "karşılaştırması ve sapma (revize − gerçekleşen; eksi = bütçe aşımı)."
            ),
            "input_schema": {"type": "object", "properties": {
                "project_id": pid, "cost_category": {"type": "string"},
            }},
        },
        {
            "name": "get_retention_summary",
            "description": (
                "Teminat/hakediş kesintisi (retention): hakediş faturalarında tutulan "
                "teminat tutarları, proje bazında toplam ve ilgili faturalar."
            ),
            "input_schema": {"type": "object", "properties": {"project_id": pid}},
        },
        {
            "name": "get_assurance_findings",
            "description": (
                "Açık Finans Güvence (CR-022 anomali) bulguları: incelenmesi gereken "
                "fatura/maliyet kayıtlarını derin bağlantılarıyla döndürür. 'Hangi "
                "faturaları incelemeliyim?' sorularında kullan."
            ),
            "input_schema": {"type": "object", "properties": {
                "project_id": pid,
                "severity": {"type": "string", "enum": ["high", "medium", "low"]},
            }},
        },
        {
            "name": "studio_catalog",
            "description": (
                "Rapor Stüdyosu kataloğu: rapor/pano önermek için kullanabileceğin "
                "GEÇERLİ boyut (dimension) ve metrik kimliklerini etiketleriyle "
                "döndürür. propose_report / propose_dashboard çağırmadan ÖNCE bunu "
                "çağır; spec'teki metrics/dimensions yalnızca buradaki id'ler olmalı. "
                "status='coming_soon' olanları KULLANMA."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        # CR-011-C — ACTION tools. These do NOT change anything directly; each one
        # creates a PENDING approval request that a human must approve. Use them
        # ONLY when the user explicitly asks for an action, and always say it is a
        # proposal awaiting approval ("öneri oluşturuldu — onayınızı bekliyor").
        {
            "name": "propose_reminder",
            "description": (
                "ÖNERİ (doğrudan yazmaz): bir hatırlatıcı oluşturmayı önerir — onay "
                "bekleyen bir talep açar. Kullanıcı bir hatırlatıcı isterse (öner/oluştur/"
                "ekle/kur, 'bana ... hatırlat') MUTLAKA bunu çağır; serbest metinle geçme. "
                "Somut bir title ver; vade için `due` kullan (tarihi kendin hesaplama)."
            ),
            "input_schema": {"type": "object", "properties": {
                "title": {"type": "string"},
                "note": {"type": "string"},
                "due": {"type": "string", "enum": list(RELATIVE_DUE),
                        "description": "Göreli vade; sunucu birebir ISO tarihe çevirir. "
                                       "Açık tarih verilmediyse bunu kullan."},
                "due_date": date_s,
                "project_id": pid,
            }, "required": ["title"]},
        },
        {
            "name": "propose_flag_invoice",
            "description": (
                "ÖNERİ (doğrudan yazmaz): bir hakediş faturasını veya maliyet kaydını "
                "incelenmek üzere işaretlemeyi önerir — onay bekleyen bir talep açar. "
                "target_id, get_assurance_findings / query_* araçlarından gelen kayıt "
                "kimliği olmalı."
            ),
            "input_schema": {"type": "object", "properties": {
                "target_kind": {"type": "string", "enum": ["client_invoice", "cost_entry"]},
                "target_id": {"type": "string", "description": "Hedef kayıt UUID"},
                "reason": {"type": "string"},
                "project_id": pid,
            }, "required": ["target_kind", "target_id", "reason"]},
        },
        {
            "name": "propose_followup_task",
            "description": (
                "ÖNERİ (doğrudan yazmaz): bir takip görevi / onay talebi oluşturmayı "
                "önerir — onay bekleyen bir talep açar. Kullanıcı bir görev/iş öğesi "
                "isterse kullan."
            ),
            "input_schema": {"type": "object", "properties": {
                "title": {"type": "string"},
                "note": {"type": "string"},
                "project_id": pid,
            }, "required": ["title"]},
        },
        {
            "name": "propose_report",
            "description": (
                "ÖNERİ/TASLAK (hiçbir şey yazmaz): kullanıcının istediği bir Rapor "
                "Stüdyosu raporu için bir TASLAK hazırlar — kayıt OLUŞTURMAZ. "
                "Kullanıcı bir rapor isterse ('… raporu yap/oluştur', 'şunu gösteren "
                "bir rapor') VEYA mevcut taslağı değiştirmek isterse MUTLAKA bunu "
                "çağır; serbest metinle geçme. ÖNCE studio_catalog ile geçerli "
                "metrik/boyut kimliklerini al, spec'i o kimliklerle kur (metrics "
                "ZORUNLU). Title açıklayıcı ve Türkçe olsun. Oluşturma yalnızca "
                "kullanıcı OLUŞTUR'a basınca olur; sen 'oluşturdum' deme."
            ),
            "input_schema": {"type": "object", "properties": {
                "title": {"type": "string"},
                "spec": spec_obj,
                "visibility": {"type": "string", "enum": ["private", "company"]},
                "project_id": pid,
            }, "required": ["title", "spec"]},
        },
        {
            "name": "propose_dashboard",
            "description": (
                "ÖNERİ/TASLAK (hiçbir şey yazmaz): birden çok widget içeren bir Rapor "
                "Stüdyosu panosu için bir TASLAK hazırlar — kayıt OLUŞTURMAZ. "
                "Kullanıcı bir pano/gösterge paneli isterse ('… panosu yap', 'bir pano "
                "oluştur') VEYA mevcut taslağı değiştirmek isterse bunu çağır. ÖNCE "
                "studio_catalog ile kimlikleri al. Her veri widget'ı (kpi/chart/table) "
                "bir spec içermeli; her widget benzersiz bir id ve bir layout "
                "(x,y,w,h) almalı. Oluşturma yalnızca kullanıcı OLUŞTUR'a basınca "
                "olur; sen 'oluşturdum' deme."
            ),
            "input_schema": {"type": "object", "properties": {
                "title": {"type": "string"},
                "widgets": {"type": "array", "items": widget_obj},
                "date_range": {"type": "object",
                               "description": "Pano geneli tarih: {preset} veya {from,to}."},
                "visibility": {"type": "string", "enum": ["private", "company"]},
                "project_id": pid,
            }, "required": ["title", "widgets"]},
        },
        {
            "name": "propose_skill",
            "description": (
                "ÖNERİ/TASLAK (hiçbir şey yazmaz): kullanıcının TEKRAR EDEN bir "
                "teslimatını (örn. 'her ay … Excel raporu') bir BECERİ (Uygulama) "
                "taslağına dönüştürür — kayıt OLUŞTURMAZ. Beceri = kaydedilen, yeniden "
                "çalıştırılabilir bir dosya tarifidir; çalıştırıldığında CANLI veriden "
                "gerçek bir Excel/PDF üretir. Kullanıcı 'bir beceri/uygulama yap', "
                "'her ay … çıkaran bir şey kur', 'şunu otomatikleştir' derse VEYA mevcut "
                "bir beceri taslağını değiştirmek isterse bunu çağır. ÖNCE studio_catalog "
                "ile geçerli metrik/boyut kimliklerini al; widgets'ı SADECE o kimliklerle "
                "kur (her veri widget'ı bir spec, benzersiz id ve layout (x,y,w,h) almalı; "
                "rapor stüdyosu panosuyla AYNI yapı). format 'xlsx' veya 'pdf'. instruction "
                "alanına kullanıcının kendi cümlesini (serbest metin) koy. Talep bir DÖNEM "
                "ima ediyorsa ('her ay', 'son 3 ay', 'bu yıl') widget spec'lerinde VEYA "
                "date_range'de GÖRELİ ön ayar kullan ({preset: bu_ay|gecen_ay|son_3_ay|"
                "son_6_ay|son_12_ay|bu_yil|gecen_yil|bu_ceyrek|gecen_ceyrek}); tarihi MUTLAK "
                "değere ÇEVİRME — böylece her çalıştırmada dönem kendiliğinden ilerler. "
                "Bir PROJE ömrü analizi/raporuysa (yakın dönem AÇIKÇA istenmediyse) "
                "date_range'i VARSAYILAN olarak {preset: tum_zamanlar} (Tüm zamanlar) yap — "
                "yoksa verisi geçmiş yıllarda olan bir projede aylık nakit/maliyet sıfır "
                "çıkar; uzun aralıkta month yerine quarter/year grain seç. "
                "Hiçbir sayı ÜRETME: dosyadaki tüm rakamlar çalışma anında motordan gelir. "
                "BIR PROJEYE ÖZELSE: önce list_projects ile projeyi bul, id'sini "
                "project_scope'a koy (çalışma anında her widget o projeye kapsanır) ve "
                "gelir modeline göre doğru metrikleri seç (sell-side → revenue/"
                "unit_sales_revenue; hakediş/maliyet_kar → hakediş). Adı çözemezsen "
                "OLUŞTURMA, SOR. "
                "Kayıt yalnızca kullanıcı 'Beceri olarak kaydet'e basınca olur; "
                "'oluşturdum' deme."
            ),
            "input_schema": {"type": "object", "properties": {
                "name": {"type": "string", "description": "Becerinin kısa Türkçe adı"},
                "widgets": {"type": "array", "items": widget_obj},
                "format": {"type": "string", "enum": ["xlsx", "pdf"]},
                "instruction": {"type": "string",
                                "description": "Kullanıcının serbest metin talebi (saklanır)"},
                "date_range": {"type": "object",
                               "description": "Beceri geneli tarih: {preset} (göreli) veya {from,to}."},
                "visibility": {"type": "string", "enum": ["private", "company"]},
                "project_scope": {"type": "string",
                                  "description": (
                                      "Beceri tek bir projeye özelse o projenin id'si "
                                      "(list_projects'ten). Çalışma anında her widget bu "
                                      "projeye kapsanır. Tüm şirket için boş bırak.")},
                "project_id": pid,
            }, "required": ["name", "widgets", "format"]},
        },
        {
            "name": "run_skill",
            "description": (
                "Kayıtlı bir BECERİYİ (Uygulama) ÇALIŞTIRIR. SALT-OKUNUR ve onay "
                "GEREKTİRMEZ: işletme verisini DEĞİŞTİRMEZ, yalnızca becerinin planını "
                "canlı veriyle çalıştırıp gerçek bir dosya (Excel/PDF) üretir ve bir "
                "indirme bağlantısı döndürür. Kullanıcı 'şu beceriyi çalıştır', '… "
                "uygulamasını çalıştır/üret' derse ve elinde becerinin kimliği (skill_id) "
                "varsa bunu çağır. Dosyadaki tüm rakamlar motordan gelir — sen sayı üretme. "
                "Sonucu indirme kartı olarak göster; 'dosya üretildi' de."
            ),
            "input_schema": {"type": "object", "properties": {
                "skill_id": {"type": "string", "description": "Çalıştırılacak becerinin UUID'si"},
            }, "required": ["skill_id"]},
        },
        {
            "name": "create_chart",
            "description": (
                "Az önce hesapladığın herhangi bir zaman serisini (aylık kırılım) veya "
                "kategori/proje kırılımını GÖRSELLEŞTİRMEK için bunu kullan. Bir kırılım "
                "ürettiysen (özellikle tedarikçi harcaması: aylara göre kategori çizgileri + "
                "toplam çizgi) bu aracı çağır. Veri ICAT ETME — yalnızca araç sonuçlarındaki "
                "sayıları kullan."
            ),
            "input_schema": {"type": "object", "properties": {
                "chart_type": {"type": "string", "enum": ["line", "bar", "composed"]},
                "title": {"type": "string"},
                "x_key": {"type": "string"},
                "series": {"type": "array", "items": {"type": "object", "properties": {
                    "key": {"type": "string"}, "label": {"type": "string"},
                    "type": {"type": "string", "enum": ["line", "bar"]},
                    "color": {"type": "string"},
                }, "required": ["key", "label", "type"]}},
                "data": {"type": "array", "items": {"type": "object"}},
                "currency": {"type": "string", "enum": ["TRY", "EUR", "USD"]},
                "source_note": {"type": "string"},
            }, "required": ["chart_type", "title", "x_key", "series", "data"]},
        },
    ]


# --------------------------------------------------------------------------- #
# Domain scoping (CR-011-B §2.1) — the dock foundation.
# ONE engine, many scopes (§0.2.3 — do NOT fork): a scope layers a Turkish
# domain preamble + a prioritized read-only tool subset + a cheap pre-loaded
# headline figure. null / "genel" = today's general agent, unchanged.
# --------------------------------------------------------------------------- #
# CR-035: studio_catalog is always available so the agent can author a report/pano
# from any scope (the propose_* action tools are already always-on via ACTION_TOOL_NAMES).
# CR-044: run_skill (read-only file generation) is likewise always available.
ALWAYS_SCOPED_TOOLS = {"create_chart", "list_projects", "studio_catalog", "run_skill"}

SCOPES: dict[str, dict] = {
    "gider": {
        "label": "Gider",
        "preamble": (
            "Sen YAPI Gider Agent'ısın. Maliyet/gider kayıtları, tedarikçi harcamaları, "
            "bütçe-gerçekleşen sapması ve maliyet kontrolüne odaklan. Soruları gider "
            "perspektifinden yanıtla; gelir/hakediş ayrıntısına yalnızca gerekirse gir."
        ),
        "tools": ["query_cost_entries", "get_vendor_spend", "compare_vendors",
                  "get_budget_variance", "get_project_financials"],
    },
    "gelir": {
        "label": "Gelir",
        "preamble": (
            "Sen YAPI Gelir Agent'ısın. Hakediş/işveren faturaları, tahsilatlar, açık "
            "alacaklar ve teminat kesintilerine odaklan. Soruları gelir/tahsilat "
            "perspektifinden yanıtla."
        ),
        "tools": ["query_client_invoices", "get_retention_summary",
                  "get_overdue_payments", "get_project_financials"],
    },
    "finans": {
        "label": "Finans",
        "preamble": (
            "Sen YAPI Finans Agent'ısın. Nakit akışı, kârlılık, vadesi geçmiş "
            "ödeme/tahsilatlar ve genel finansal sağlığa odaklan. Bütçe sapması ve "
            "güvence bulgularını da gerektiğinde kullan."
        ),
        "tools": ["get_cashflow", "get_overdue_payments", "get_project_financials",
                  "get_budget_variance", "get_assurance_findings"],
    },
    "hakedis": {
        "label": "Hakediş",
        "preamble": (
            "Sen YAPI Hakediş Agent'ısın. Hakediş faturaları, teminat kesintileri, alt "
            "yüklenici hakedişleri ve tahsilata odaklan. Soruları hakediş "
            "perspektifinden yanıtla."
        ),
        "tools": ["query_client_invoices", "get_retention_summary",
                  "query_subcontractors", "get_overdue_payments"],
    },
    "belge": {
        "label": "Belge",
        "preamble": (
            "Sen YAPI Belge Agent'ısın. Fatura/maliyet kayıtları ve incelenmesi gereken "
            "belgelere (Finans Güvence bulguları) odaklan. 'Hangi belgeleri/faturaları "
            "incelemeliyim?' türü soruları derin bağlantılı kaynaklarla yanıtla."
        ),
        "tools": ["get_assurance_findings", "query_cost_entries", "query_client_invoices"],
    },
}


def scoped_tool_schemas(scope: str | None) -> list[dict]:
    """Return the tool schemas available for ``scope``: the scope's prioritized
    subset + always-on tools (create_chart, list_projects). Unknown/None scope =
    the full catalogue (genel)."""
    schemas = build_tool_schemas()
    cfg = SCOPES.get(scope or "")
    if not cfg:
        return schemas
    # Action tools (propose-only) stay available in every scope (§3.1).
    allowed = set(cfg["tools"]) | ALWAYS_SCOPED_TOOLS | ACTION_TOOL_NAMES
    return [t for t in schemas if t["name"] in allowed]


def _scope_preamble(scope: str | None) -> str:
    cfg = SCOPES.get(scope or "")
    return cfg["preamble"] if cfg else ""


def _scope_context(db: Session, company_id, scope: str | None, today: date) -> str:
    """Cheap pre-loaded headline figure for the scope (§2.1), reusing the existing
    SQL-aggregating tools. Defensive: any failure returns '' (never breaks the
    request) so a scoped chat degrades to no-context rather than erroring."""
    cfg = SCOPES.get(scope or "")
    if not cfg:
        return ""
    try:
        if scope == "gider":
            s = tools.query_cost_entries(
                db, company_id, date_from=date(today.year, 1, 1), date_to=today)["summary"]
            return f"Bu yıl toplam gider (matrah): {s['total_amount_try']} ₺ ({s['entry_count']} kayıt)."
        if scope in ("gelir", "hakedis"):
            s = tools.query_client_invoices(db, company_id)["summary"]
            return (f"Açık alacak (tahsil edilmemiş): {s['total_outstanding_try']} ₺; "
                    f"toplam hakediş: {s['invoice_count']} adet.")
        if scope == "finans":
            s = tools.get_overdue_payments(db, company_id, today=today)["summary"]
            return (f"Vadesi geçmiş ödenecek: {s['overdue_payable_total_try']} ₺ "
                    f"({s['overdue_payable_count']}); vadesi geçmiş tahsilat: "
                    f"{s['overdue_receivable_total_try']} ₺ ({s['overdue_receivable_count']}).")
        if scope == "belge":
            s = tools.get_assurance_findings(db, company_id)["summary"]
            return f"Açık güvence bulgusu: {s['finding_count']} adet (incelenmesi önerilen kayıtlar)."
    except Exception as exc:  # pre-loading must never fail the request
        logger.warning("scope context failed for %s: %s", scope, exc)
    return ""


# --------------------------------------------------------------------------- #
# Tool execution
# --------------------------------------------------------------------------- #
def _coerce_params(allowed: set[str], raw: dict) -> dict:
    """Whitelist params (drops any company_id) and parse ISO date strings."""
    params: dict = {}
    for k, v in (raw or {}).items():
        if k not in allowed:
            continue
        if k in _DATE_PARAMS and isinstance(v, str) and v:
            try:
                v = date.fromisoformat(v[:10])
            except ValueError:
                continue
        params[k] = v
    return params


# Citation amount: first present money field on the record.
_CITATION_AMOUNT_KEYS = (
    "total_with_vat_try", "amount_try", "outstanding_try", "remaining_try", "net_due_try",
)


def _citation_type(link: str) -> str:
    """Type from the record's actual source (its deep_link target), NOT from the
    presence of an invoice_number — a cost entry can carry one too."""
    if "/invoices?highlight=" in link:
        return "client_invoice"
    if "/subcontractors?highlight=" in link:
        return "subcontractor"
    if "/dashboard?highlight=" in link:
        return "cost_entry"
    return "record"


def _citation_amount(rec: dict) -> str:
    for k in _CITATION_AMOUNT_KEYS:
        v = rec.get(k)
        if v not in (None, ""):
            # Whole-TRY, Turkish grouping (e.g. "2.778.000 ₺").
            return f"{format_number_tr(v, 0)} ₺"
    return ""


def _add_citations(result: dict, citations: list, seen: set) -> None:
    """Derive citation chips from a tool result's highlightable records.

    Labels carry a Turkish-formatted amount and a distinguishing token so that
    several chips for the same vendor are not identical."""
    for rec in (result.get("records") or []):
        link = rec.get("deep_link", "")
        rid = rec.get("id")
        if not rid or "highlight=" not in link or rid in seen:
            continue
        seen.add(rid)
        ctype = _citation_type(link)
        amount = _citation_amount(rec)

        if ctype == "client_invoice":
            head = rec.get("invoice_number") or "Fatura"
        elif ctype == "cost_entry":
            supplier = rec.get("supplier_name") or "Maliyet"
            # Unique-ish token so 8 same-supplier chips differ: invoice no, else
            # entry date, else cost category.
            disc = rec.get("invoice_number")
            if not disc and rec.get("entry_date"):
                disc = format_date_tr(rec["entry_date"])
            if not disc and rec.get("cost_category"):
                disc = COST_CATEGORIES.get(rec["cost_category"], rec["cost_category"])
            head = f"{supplier} · {disc}" if disc else supplier
        elif ctype == "subcontractor":
            head = rec.get("name") or "Alt Yüklenici"
        else:
            head = rec.get("name") or rid

        label = f"{head} — {amount}" if amount else head
        citations.append({"type": ctype, "id": rid, "label": label.strip(), "deep_link": link})
        if len(citations) >= 25:
            return


def _apply_relative_due(raw: dict, params: dict, today: date) -> None:
    """CR-011 Item 2 — resolve a model-supplied named ``due`` to a literal ISO
    ``due_date`` on the SERVER (§0.2.5). Never overrides an explicit due_date."""
    due = (raw or {}).get("due")
    if not due or params.get("due_date"):
        return
    d = resolve_due(due, today or date.today())
    if d is not None:
        params["due_date"] = d.isoformat()


def _apply_relative_window(allowed: set[str], raw: dict, params: dict, today: date) -> None:
    """CR-011-A §1.2 — resolve a model-supplied `relative_window` to literal
    date_from/date_to on the SERVER. Only applies to date-aware tools and never
    overrides explicit dates the model already passed (user-given dates win)."""
    rw = (raw or {}).get("relative_window")
    if not rw or not (_DATE_PARAMS & allowed):
        return
    if "date_from" in params or "date_to" in params:
        return
    df, dt = resolve_window(rw, today or date.today())
    if df is not None:
        params["date_from"] = df
    if dt is not None:
        params["date_to"] = dt


def execute_tool(db: Session, company_id, name: str, tool_input: dict,
                 charts: list, citations: list, seen: set, today: date | None = None,
                 user_id=None, proposed_actions: list | None = None) -> dict:
    """Run one tool with company_id injected server-side. Never raises — returns
    an error dict so the model can recover within the loop. A relative date window
    (if any) is resolved to literal ISO dates here (§1.2), never by the model.

    CR-011-C: ACTION tools are routed separately — they create a PENDING approval
    request (propose-only, §0.2.1) and the proposal is appended to
    ``proposed_actions`` for the UI. They require a ``user_id`` (requested_by)."""
    if name == "create_chart":
        try:
            spec = tools.create_chart(**(tool_input or {}))
        except tools.ToolError as exc:
            return {"error": str(exc)}
        charts.append(spec)
        return {"ok": True, "chart": spec}

    # CR-044 — run_skill: READ-ONLY file generation (NOT a propose tool, NOT a direct
    # business mutation). Runs a saved skill's plan through the trusted engine and
    # returns a download card. Requires a session (user_id). Like create_chart it is
    # special-cased here and kept OUT of both registries (the read-only TOOL_REGISTRY
    # guarantee and the ACTION_TOOL_NAMES exact set both stay intact).
    if name == "run_skill":
        if user_id is None:
            return {"error": "Bu eylem için oturum bağlamı gerekli."}
        from app.services import skills as skills_service
        result = skills_service.run_skill_tool(
            db, company_id, user_id, (tool_input or {}).get("skill_id")
        )
        pa = result.get("proposed_action") if isinstance(result, dict) else None
        if pa is not None and proposed_actions is not None:
            proposed_actions.append(pa)
        return result

    # CR-011-C — propose-only action tools (never a direct mutation).
    action = ACTION_TOOL_REGISTRY.get(name)
    if action is not None:
        if user_id is None:
            return {"error": "Bu eylem için oturum bağlamı gerekli."}
        func, allowed = action
        params = _coerce_params(allowed, tool_input)
        if name == "propose_reminder":
            _apply_relative_due(tool_input, params, today)
        try:
            result = func(db, company_id, user_id, **params)
        except actions.ActionError as exc:
            return {"error": str(exc)}
        except TypeError as exc:  # missing/invalid params
            return {"error": f"Eylem parametreleri geçersiz: {exc}"}
        pa = result.get("proposed_action") if isinstance(result, dict) else None
        if pa is not None and proposed_actions is not None:
            proposed_actions.append(pa)
        return result

    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return {"error": f"Bilinmeyen araç: {name}"}
    func, allowed = entry
    params = _coerce_params(allowed, tool_input)
    _apply_relative_window(allowed, tool_input, params, today)
    try:
        result = func(db, company_id, **params)
    except tools.ToolError as exc:
        return {"error": str(exc)}
    except TypeError as exc:  # missing required param etc.
        return {"error": f"Araç parametreleri geçersiz: {exc}"}
    _add_citations(result, citations, seen)
    return result


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
def _text_of(content) -> str:
    return "".join(b.text for b in content if getattr(b, "type", "") == "text").strip()


def _thinking_of(content) -> str:
    """The model's extended-thinking text (CR-011 rich steps, PART B). Reads only
    ``thinking`` blocks, so it never touches the answer text (_text_of keeps the
    answer clean — it only joins ``text`` blocks)."""
    return "".join(
        getattr(b, "thinking", "") for b in content if getattr(b, "type", "") == "thinking"
    ).strip()


def _accumulate_usage(total: dict, usage) -> None:
    """Sum input/output tokens off one model response's ``usage`` (PART C). With
    thinking on, thinking tokens are already counted in output_tokens. Missing /
    None usage (e.g. test doubles) is ignored so the shape is always present."""
    if usage is None:
        return
    total["input_tokens"] += int(getattr(usage, "input_tokens", 0) or 0)
    total["output_tokens"] += int(getattr(usage, "output_tokens", 0) or 0)


def _summary_aggregates(summary: dict) -> dict:
    """Keep only the SCALAR aggregates (totals/counts) from a tool result's
    ``summary`` (PART A). Nested breakdowns (by_month, by_project, ranking,
    matched_names, forecast_at_completion, …) and raw ``records`` never leave the
    server — the surfaced payload is aggregates-only, not row data, regardless of
    what the frontend chooses to render."""
    return {k: v for k, v in summary.items() if isinstance(v, (str, int, float, bool))}


# CR-011-A §4.1 — real-time step labels (Turkish), driven by the stream's `step`
# events so the UI indicator reflects what the agent is actually doing.
_STEP_LABELS = {
    "list_projects": "Projeler taranıyor…",
    "get_project_financials": "Proje finansalları inceleniyor…",
    "query_cost_entries": "Maliyet kayıtları inceleniyor…",
    "query_client_invoices": "Hakedişler inceleniyor…",
    "query_subcontractors": "Alt yükleniciler inceleniyor…",
    "get_vendor_spend": "Tedarikçi harcamaları inceleniyor…",
    "compare_vendors": "Tedarikçiler karşılaştırılıyor…",
    "get_cashflow": "Nakit akışı hesaplanıyor…",
    "get_overdue_payments": "Vadesi geçmiş ödemeler taranıyor…",
    "get_equipment_utilisation": "Ekipman kullanımı inceleniyor…",
    "get_budget_variance": "Bütçe sapması hesaplanıyor…",
    "get_retention_summary": "Teminat kesintileri inceleniyor…",
    "get_assurance_findings": "Güvence bulguları taranıyor…",
    "create_chart": "Grafik hazırlanıyor…",
    "propose_reminder": "Hatırlatıcı önerisi hazırlanıyor…",
    "propose_flag_invoice": "İnceleme önerisi hazırlanıyor…",
    "propose_followup_task": "Görev önerisi hazırlanıyor…",
    # CR-035 — Report Studio AI authoring.
    "studio_catalog": "Stüdyo kataloğu inceleniyor…",
    "propose_report": "Rapor önerisi hazırlanıyor…",
    "propose_dashboard": "Pano önerisi hazırlanıyor…",
    # CR-044 — Skills (Beceriler).
    "propose_skill": "Beceri taslağı hazırlanıyor…",
    "run_skill": "Beceri çalıştırılıyor…",
}


def _step_label(name: str) -> str:
    return _STEP_LABELS.get(name, "Veriler inceleniyor…")


# CR-011-C — propose-only action guidance (always present; the agent has action
# tools in every scope). Reinforces the §0.2.1 invariant in the model's own words.
_ACTION_GUIDANCE = (
    "\n\nEYLEM ARAÇLARI (propose_reminder, propose_flag_invoice, propose_followup_task, "
    "propose_report, propose_dashboard, propose_skill, run_skill): "
    "Bu araçların HİÇBİRİ DOĞRUDAN bir şey YAZMAZ. propose_reminder / "
    "propose_flag_invoice / propose_followup_task ONAY BEKLEYEN bir öneri oluşturur "
    "(/approvals'tan onaylanınca uygulanır). propose_report / propose_dashboard ise "
    "yalnızca bir TASLAK hazırlar (hiçbir şey yazmaz) — kullanıcı sohbette düzenler ve "
    "OLUŞTUR'a basınca kendi raporunu/panosunu kendisi oluşturur.\n"
    "NE ZAMAN ÇAĞIRMALISIN (ZORUNLU): Kullanıcı somut bir EYLEM yapılmasını isterse, "
    "serbest metinle yanıt verip geçme — ilgili aracı MUTLAKA çağır:\n"
    "- 'hatırlatıcı öner/oluştur/ekle/kur', 'bana ... hatırlat', 'şunu hatırlat/unutturma' → "
    "propose_reminder. Somut bir Türkçe title ver; vade için `due` parametresini kullan "
    "(bugun/yarin/gelecek_hafta/iki_hafta/ay_sonu/gelecek_ay) — tarihi KENDİN HESAPLAMA. "
    "Kullanıcı açık bir tarih verdiyse onu due_date olarak kopyala.\n"
    "- 'şu faturayı/maliyeti incele(meye al)', '... incele olarak işaretle', 'flag' → "
    "propose_flag_invoice (target_kind + target_id + reason). target_id'yi query_* / "
    "get_assurance_findings sonuçlarından al.\n"
    "- 'takip görevi oluştur', 'görev/yapılacak ekle' → propose_followup_task (somut title).\n"
    "- 'rapor yap/oluştur', 'şunu gösteren bir rapor', 'X'e göre Y raporu çıkar' VEYA "
    "mevcut taslakta değişiklik ('aylık yap', 'şu metriği ekle', 'alacakları çıkar') → "
    "propose_report. ÖNCE studio_catalog'u çağırıp geçerli metrik/boyut kimliklerini "
    "al; spec'i SADECE o kimliklerle kur (metrics ZORUNLU; kırılım için dimensions; "
    "uygun viz: line/area/bar/kpi/table). Önce kısaca ne hazırlayacağını söyle, sonra "
    "aracı çağırıp TASLAĞI ekle; kullanıcıya sohbette düzenleyebileceğini veya "
    "OLUŞTUR'a basabileceğini belirt.\n"
    "- 'pano/gösterge paneli yap/oluştur', 'şunları tek ekranda gösteren bir pano' VEYA "
    "mevcut pano taslağında değişiklik → propose_dashboard. ÖNCE studio_catalog; her "
    "veri widget'ı (kpi/chart/table) bir spec, benzersiz bir id ve bir layout "
    "(x,y,w,h) almalı. TASLAĞI ekle ve kullanıcıya düzenleyebileceğini veya OLUŞTUR'a "
    "basabileceğini söyle.\n"
    "- 'bir beceri/uygulama yap', 'her ay … (Excel/PDF) çıkaran bir şey kur', 'şu raporu "
    "otomatikleştir/kaydet' VEYA mevcut bir beceri taslağında değişiklik → propose_skill. "
    "Beceri = kaydedilen, yeniden çalıştırılabilir bir DOSYA tarifi; çalıştırılınca canlı "
    "veriden gerçek Excel/PDF üretir. ÖNCE studio_catalog; widgets'ı panodaki gibi kur, "
    "format ('xlsx'/'pdf') seç, instruction'a kullanıcının cümlesini koy. Talep bir DÖNEM "
    "ima ediyorsa ('her ay', 'son 3 ay', 'bu yıl') GÖRELİ ön ayar kullan "
    "({preset: bu_ay|son_3_ay|bu_yil…}); tarihi MUTLAK değere çevirme (her çalıştırmada "
    "dönem ilerlesin). Bir PROJE ömrü analizi/raporu ise (yakın dönem AÇIKÇA istenmediyse) "
    "date_range'i VARSAYILAN olarak `all_time` (tum_zamanlar) yap — yoksa veri geçmiş "
    "yıllardaysa aylık nakit/maliyet SIFIR çıkar. TASLAĞI ekle; kullanıcı 'Beceri olarak "
    "kaydet'e basınca kaydeder.\n"
    "- 'şu beceriyi/uygulamayı çalıştır/üret' (elinde skill_id varsa) → run_skill. Bu "
    "SALT-OKUNUR bir dosya üretimidir (onay gerekmez, işletme verisini değiştirmez); "
    "sonucu indirme kartı olarak göster ve 'dosya üretildi' de.\n"
    "DOĞRU VERİ (rapor/pano/beceri yazarken ZORUNLU):\n"
    "1) PROJE KAPSAMI: Kullanıcı bir proje ADI verdiyse ('DGN Martı için …') ÖNCE "
    "list_projects ile o projeyi bul. Tam eşleşen TEK bir proje yoksa veya birden fazla "
    "aday varsa (örn. iki '213 Ada 1 Parsel') OLUŞTURMA — kullanıcıya hangi projeyi "
    "kastettiğini SOR. Çözülünce projenin id'sini propose_skill'de project_scope'a koy "
    "VE her veri widget'ının spec.filters'ına {field:'project',op:'=',value:<id>} ekle. "
    "Asla bir projenin adıyla TÜM ŞİRKETİ kapsayan bir rapor üretme.\n"
    "2) GELİR MODELİ: list_projects'teki revenue_model'e bak. Sell-side ise "
    "(kat_karsiligi/yap_sat/hasilat_paylasimi) gelir için revenue/unit_sales_revenue "
    "kullan; progress_billing/billing_vs_contract (HAKEDİŞ) KULLANMA — hakediş bu "
    "modelde anlamsızdır. hakedis/maliyet_kar ise hakediş metriklerini kullan; "
    "unit_sales_revenue/*_per_m2/irr/roi KULLANMA. (Motor zaten uygunsuz metriği '–' "
    "yapar; yine de doğru metriği seç.)\n"
    "3) Snapshot (windowed=false) bir metriği (hakediş, forecast, *_per_m2, irr, roi, "
    "budget, revenue) 'month'a göre kırılan bir TABLOYA koyma — onları KPI/tek değer yap.\n"
    "4) ZAMAN PENCERESİ: Bir projenin ANALİZİ / ÖZETİ / RAPORU (proje ömrü görünümü) "
    "için date_range'i VARSAYILAN olarak `all_time` (Tüm zamanlar) yap — `bu_yil` / "
    "`son_3_ay` DEĞİL. Çoğu projenin verisi geçmiş yıllardadır; dar/yakın bir pencere "
    "aylık nakit/maliyeti SIFIR gösterir (windowed metrikler boş kalır). Yakın pencereyi "
    "(`bu_ay`/`son_3_ay`/`gecen_ay`…) YALNIZCA kullanıcı açıkça isterse kullan ('bu ay', "
    "'son 3 ay', 'geçen ay'). list_projects'teki start_date/actual_end_date projenin "
    "GERÇEK aralığını verir — pencereyi onu kapsayacak şekilde seç. UZUN aralıklar için "
    "(birkaç yıl) aylık 30-40 satır yerine `quarter` veya `year` grain kullan; kısa "
    "aralıklar için `month`. Dönemi gerçek aralıktan etiketle (motor meta.date_range'i "
    "doğru döndürür) — asla sabit yakın bir aralık yazma.\n"
    "5) GÖRSEL/GRAFİK SEÇİMİ: Her widget'a veri ŞEKLİNE uygun bir viz seç — zaman "
    "serisi (month/quarter/year) için `line` (tek metrik/kümülatif) veya `area`; "
    "bir kategori/vendor/tip kırılımı için `bar`; tek değer/anlık için `kpi`. "
    "Bir rapor/panoda AZ SAYIDA, yüksek değerli grafik kullan — HER bölüme/tabloya "
    "grafik koyma (bu bir anti-desen). Motor grafiği veri şekline göre otomatik seçer "
    "ve uygun olmayan şekillerde (anlık/tek değer/≤3 satır) grafiği ELER; tablo widget'ı "
    "da şekil uygunsa kendi grafiğini kazanır — bu yüzden gereksiz/tekrar eden grafik "
    "widget'ı ekleme.\n"
    "Birden fazla eylem istenirse her biri için AYRI bir araç çağrısı yap.\n"
    "NE ZAMAN ÇAĞIRMAMALISIN: Kullanıcı yalnızca GENEL TAVSİYE veya bir öneri/yapılacaklar "
    "LİSTESİ isterse (örn. 'ne yapmalıyım', 'önerilerin neler') eylem aracı çağırma; "
    "serbest metinle yanıtla.\n"
    "Sonucu bildirirken ASLA 'yaptım/oluşturdum/işaretledim' deme. "
    "Hatırlatıcı/işaret/görev için 'öneri oluşturuldu, onayınızı bekliyor' de ve "
    "/approvals sayfasına yönlendir. Rapor/pano için 'taslağı hazırladım — sohbette "
    "düzenleyebilir veya Oluştur'a basabilirsin' de; oluşturmayı kullanıcı yapar."
)


def _draft_context(draft) -> str:
    """CR-039 — summarize the active authoring DRAFT the user is refining so the
    model edits the REAL spec instead of rebuilding it from prose. Defensive:
    returns "" for any malformed/absent draft (never raises). Request-only context,
    mirrors how ``scope``/``report_id`` are injected — it adds context, not a write
    path (the agent still writes nothing; creation is the user's OLUŞTUR click)."""
    if not isinstance(draft, dict):
        return ""
    try:
        kind = draft.get("kind")
        title = (draft.get("title") or "").strip()
        if kind == "draft_report":
            spec = draft.get("spec")
            if not isinstance(spec, dict):
                return ""
            return (
                f"Kullanıcı şu RAPOR taslağını düzenliyor: «{title or 'Rapor'}». "
                f"Mevcut spec — metrikler: {spec.get('metrics')}; "
                f"boyutlar: {spec.get('dimensions') or '—'}; "
                f"görsel: {spec.get('viz', 'table')}; "
                f"tarih: {spec.get('date_range') or 'varsayılan'}. "
                "Sıfırdan başlama — bu spec'i kullanıcının isteğine göre GÜNCELLE ve "
                "propose_report ile yeni taslağı öner. Hiçbir şey oluşturma; "
                "'oluşturdum' deme — oluşturma kullanıcının OLUŞTUR butonuyla olur."
            )
        if kind == "draft_dashboard":
            widgets = draft.get("widgets")
            n = len(widgets) if isinstance(widgets, list) else 0
            return (
                f"Kullanıcı şu PANO taslağını düzenliyor: «{title or 'Pano'}» "
                f"({n} widget). Sıfırdan başlama — mevcut widget'ları kullanıcının "
                "isteğine göre GÜNCELLE ve propose_dashboard ile yeni taslağı öner. "
                "Hiçbir şey oluşturma; 'oluşturdum' deme — oluşturma kullanıcının "
                "OLUŞTUR butonuyla olur."
            )
        if kind == "draft_skill":
            plan = draft.get("plan") if isinstance(draft.get("plan"), dict) else {}
            widgets = plan.get("widgets")
            n = len(widgets) if isinstance(widgets, list) else 0
            fmt = draft.get("format") or plan.get("format") or "xlsx"
            return (
                f"Kullanıcı şu BECERİ taslağını düzenliyor: «{title or 'Beceri'}» "
                f"({n} bölüm, biçim: {fmt}). Sıfırdan başlama — mevcut planı (widgets + "
                "date_range) kullanıcının isteğine göre GÜNCELLE ve propose_skill ile yeni "
                "taslağı öner; biçim/dönem değişikliklerini de uygula. Dönem ima edilirse "
                "GÖRELİ ön ayar kullan (tarihi mutlak değere çevirme). Hiçbir şey "
                "oluşturma/çalıştırma; 'oluşturdum' deme — kaydetme kullanıcının 'Beceri "
                "olarak kaydet' butonuyla olur."
            )
    except Exception:  # malformed draft must never break the turn
        return ""
    return ""


def _build_system(today: date | None, project_id, scope: str | None = None,
                  scope_context: str = "", extra_context: str = "",
                  draft_context: str = "") -> str:
    """Assemble the system prompt: base + server-date rules + action guidance +
    optional domain `scope` preamble + cheap pre-loaded scope context + active
    project (§2.1, §3.1) + optional CR-035 grounding (e.g. "Bu rapor hakkında sor")
    + optional CR-039 authoring-draft context (the spec the user is refining)."""
    system = SYSTEM_PROMPT + _date_guidance(today or date.today()) + _ACTION_GUIDANCE
    pre = _scope_preamble(scope)
    if pre:
        system += "\n\nALAN ODAĞI: " + pre
    if scope_context:
        system += "\n\nALAN BAĞLAMI (ön-yükleme): " + scope_context
    if extra_context:
        # CR-035 — grounded read-only Q&A over a specific saved report (spec + run
        # result). Read-only: it adds context, never a write path.
        system += "\n\nRAPOR BAĞLAMI (salt-okunur): " + extra_context
    if draft_context:
        # CR-039 — the authoring draft the user is editing (refine-by-chat). The
        # model updates this spec and re-proposes a draft; it still writes nothing.
        system += "\n\nTASLAK BAĞLAMI (düzenleme): " + draft_context
    if project_id is not None:
        system += (
            f"\n\nAKTİF PROJE BAĞLAMI: Kullanıcı şu an proje {project_id} bağlamında "
            "çalışıyor. Aksi belirtilmedikçe bu projeyi varsay."
        )
    return system


def _agent_events(db: Session, company_id, messages: list[dict], project_id, user_id,
                  today: date, stream: bool, scope: str | None = None,
                  extra_context: str = "", draft=None):
    """Shared tool-use loop, expressed as an event generator (CR-011-A §1.1).

    Yields ``{"type": "delta", "text": ...}`` for live answer tokens (streaming
    only), ``{"type": "step", "tool": ..., "label": ...}`` before each tool runs,
    and finally exactly one ``{"type": "final", "data": <result>}`` carrying the
    SAME structured payload the non-stream path has always returned (charts,
    citations, tools_used, row_counts, query_log_id, generated_at).

    Raises ai_service.AIUnavailable on a true outage / budget overrun (callers
    degrade gracefully). When ``stream`` is True a streaming call that fails mid
    flight falls back to a single non-stream call so the answer is never lost
    (§4.4 / §1.1)."""
    client = ai_service._client()  # raises AIUnavailable when no key/SDK
    tool_schemas = scoped_tool_schemas(scope)
    scope_ctx = _scope_context(db, company_id, scope, today)
    system = _build_system(today, project_id, scope, scope_ctx, extra_context,
                           _draft_context(draft))

    convo: list[dict] = [{"role": m["role"], "content": m["content"]} for m in messages]
    tools_used: list[str] = []
    row_counts: dict[str, int] = {}
    charts: list[dict] = []
    citations: list[dict] = []
    proposed_actions: list[dict] = []  # CR-011-C — pending approval proposals
    seen_citation_ids: set = set()
    # CR-011 rich steps (PART A/C): per-tool aggregate summaries surfaced in the
    # step detail, and the turn's total token usage. Both are in-session display
    # only (not persisted) — like charts/citations.
    tool_summaries: dict[str, dict] = {}
    usage_total: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

    timeout = settings.ai_agent_timeout_seconds
    started = time.monotonic()

    resp = None
    for i in range(MAX_ITERATIONS):
        # 60s server-side budget across the whole loop (§6.1).
        if time.monotonic() - started > timeout:
            logger.warning("Agent loop exceeded %ss budget", timeout)
            raise ai_service.AIUnavailable("timeout")

        force_final = i == MAX_ITERATIONS - 1
        call_kw = dict(
            model=settings.anthropic_model,
            max_tokens=settings.ai_agent_max_tokens,
            system=system,
            tools=tool_schemas,
            tool_choice={"type": "none"} if force_final else {"type": "auto"},
            messages=convo,
            timeout=timeout,
        )
        # PART B — extended thinking (env-gated, OFF by default). NEVER on the
        # forced-final iteration: the API rejects thinking + a forced tool_choice.
        # No temperature is set (thinking requires the default). Hardened so a
        # thinking/SDK incompatibility can never down the agent (§SDK-upgrade):
        #  - capability guard: only pass `thinking` if the SDK accepts it;
        #  - budget guard: it must leave room for the answer within max_tokens
        #    (skip thinking instead of crashing if mis-configured);
        #  - per-call fallback in _create_call/_stream_call retries without it.
        if (settings.ai_agent_thinking_enabled and not force_final
                and _thinking_capable(client)):
            if settings.ai_agent_max_tokens > settings.ai_agent_thinking_budget:
                call_kw["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": settings.ai_agent_thinking_budget,
                }
            else:
                logger.warning(
                    "ai_agent_thinking_budget (%s) >= ai_agent_max_tokens (%s); "
                    "thinking disabled this call to leave room for the answer.",
                    settings.ai_agent_thinking_budget, settings.ai_agent_max_tokens,
                )
        if stream:
            resp = yield from _stream_call(client, call_kw)
        else:
            resp = _create_call(client, call_kw)

        # PART C — sum token usage across every iteration of the turn.
        _accumulate_usage(usage_total, getattr(resp, "usage", None))

        if resp.stop_reason != "tool_use":
            break

        # PART A/B — this iteration's pre-tool narration (text blocks) and the
        # model's extended-thinking text, attached to each step it produced.
        iter_note = _text_of(resp.content)
        iter_thinking = _thinking_of(resp.content)

        # Append the assistant tool_use turn, then the tool_result turn. Appending
        # resp.content verbatim preserves any thinking blocks (required by the API
        # to continue a thinking turn through tool use).
        convo.append({"role": "assistant", "content": resp.content})
        results_block = []
        for block in resp.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            tools_used.append(block.name)
            if stream:
                # Real-time step indicator (§4.1): the UI clears any preamble
                # preview on a step and shows the tool's Turkish label. PART A:
                # also carry the cleaned tool args, the narration, and (PART B)
                # the thinking so the collapsed step can show real detail.
                # create_chart's args are huge (the full series/data) — skip them.
                step_input = {} if block.name == "create_chart" else dict(block.input or {})
                yield {
                    "type": "step", "tool": block.name, "label": _step_label(block.name),
                    "input": step_input, "note": iter_note, "thinking": iter_thinking,
                }
            result = execute_tool(db, company_id, block.name, dict(block.input or {}),
                                  charts, citations, seen_citation_ids, today,
                                  user_id, proposed_actions)
            if isinstance(result, dict) and "row_count" in result:
                row_counts[block.name] = row_counts.get(block.name, 0) + int(result["row_count"])
            # PART A — the tool's aggregate summary (totals/counts, never raw rows
            # nor nested breakdowns: pruned to scalars before it leaves the server).
            if isinstance(result, dict) and isinstance(result.get("summary"), dict):
                agg = _summary_aggregates(result["summary"])
                if agg:
                    tool_summaries[block.name] = agg
            results_block.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })
        convo.append({"role": "user", "content": results_block})

    answer = _text_of(resp.content) if resp is not None else ""

    # CR-024-A: capture the log row id so the answer can be linked to feedback.
    # Finalized at stream end — same data as the non-stream path (§1.1).
    query_log_id = None
    if user_id is not None:
        query_log_id = _log_query(db, company_id, user_id, messages, tools_used, row_counts)

    yield {"type": "final", "data": {
        "answer_markdown": answer,
        "charts": charts,
        "citations": citations,
        "tools_used": tools_used,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "notes": "",
        # CR-024-A (additive): surface the log id + the row counts already computed
        # above so the frontend explainability panel / feedback can use real data.
        "query_log_id": str(query_log_id) if query_log_id else None,
        "row_counts": row_counts,
        # CR-011-C — pending approval proposals (Onayla/Reddet cards). Read-only
        # answers carry an empty list, so the response shape is unchanged.
        "proposed_actions": proposed_actions,
        # CR-011 rich steps (PART A/C, additive, in-session only): per-tool
        # aggregate summaries for the step detail + the turn's total token usage.
        "tool_summaries": tool_summaries,
        "usage": usage_total,
    }}


# --------------------------------------------------------------------------- #
# Thinking safety net (SDK-upgrade hardening) — a thinking/SDK incompatibility
# must NEVER take the agent down again. Two independent guards:
#   (a) capability guard: if the installed SDK doesn't even accept `thinking`,
#       never pass it (treat the flag as OFF and warn once);
#   (b) per-call fallback: if a thinking-enabled call still fails *because of*
#       thinking, strip it and retry the SAME call once without it.
# --------------------------------------------------------------------------- #
def _thinking_capable(client) -> bool:
    """True if the installed anthropic SDK accepts a ``thinking`` kwarg on
    messages.create. The pinned 0.42.0 SDK predated it and raised TypeError, taking
    the agent down when AI_AGENT_THINKING_ENABLED flipped on — this stops that at
    the source. Introspected once (the create function is a stable object)."""
    return _create_accepts_thinking(type(client.messages).create)


@functools.lru_cache(maxsize=1)
def _create_accepts_thinking(create_fn) -> bool:
    try:
        params = inspect.signature(create_fn).parameters
    except (TypeError, ValueError):
        # Can't introspect — assume supported; the per-call fallback below covers a
        # real incompatibility, so a wrong guess here never downs the agent.
        return True
    # "Accepts `thinking`" means passing it won't raise an unexpected-kwarg
    # TypeError: either an explicit `thinking` parameter (the real SDK ≥ 0.45) or a
    # **kwargs catch-all. The pinned 0.42.0 create had neither -> correctly OFF.
    supported = "thinking" in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    if not supported:
        logger.warning(
            "Installed anthropic SDK does not accept a `thinking` parameter; "
            "treating ai_agent_thinking_enabled as OFF (upgrade the SDK to enable "
            "extended thinking)."
        )
    return supported


def _is_thinking_error(exc: Exception) -> bool:
    """True if ``exc`` is the signature of a thinking/SDK incompatibility: an
    unexpected-kwarg ``TypeError`` for ``thinking`` or an API error specifically
    about the ``thinking`` parameter. Only these trigger the strip-and-retry —
    an unrelated transport failure still degrades normally."""
    return "thinking" in str(exc).lower()


def _create_call(client, call_kw):
    """One non-stream model call; transport errors -> AIUnavailable (degrade).
    If a thinking-enabled call fails *because of* thinking, strip it and retry once
    so the user still gets a normal answer (per-call fallback, §SDK-upgrade)."""
    try:
        return client.messages.create(**call_kw)
    except ai_service.AIUnavailable:
        raise
    except Exception as exc:  # network / timeout / API error -> degrade
        if "thinking" in call_kw and _is_thinking_error(exc):
            logger.warning("thinking call failed (%s: %s); retrying without thinking",
                           type(exc).__name__, exc)
            retry_kw = {k: v for k, v in call_kw.items() if k != "thinking"}
            try:
                return client.messages.create(**retry_kw)
            except ai_service.AIUnavailable:
                raise
            except Exception as exc2:
                logger.warning("Agent Claude call failed (post-downgrade): %s: %s",
                               type(exc2).__name__, exc2)
                raise ai_service.AIUnavailable("Claude error") from exc2
        logger.warning("Agent Claude call failed: %s: %s", type(exc).__name__, exc)
        raise ai_service.AIUnavailable("Claude error") from exc


def _stream_call(client, call_kw):
    """One streaming model call: yields ``{"type": "delta", "text": ...}`` for each
    text chunk and returns the final assembled Message (with tool_use blocks) so
    the loop can continue. If streaming fails before completing, falls back to a
    single non-stream call so the answer is never lost (§1.1).

    Thinking-specific failure handling (§SDK-upgrade): strip ``thinking`` and
    recover once. If nothing has streamed yet, re-stream (the user still gets a
    *streamed* answer); if deltas were already emitted, drop to a non-stream call
    so we never re-emit the prefix and show a doubled answer."""
    emitted = False
    try:
        with client.messages.stream(**call_kw) as s:
            for chunk in s.text_stream:
                if chunk:
                    emitted = True
                    yield {"type": "delta", "text": chunk}
            return s.get_final_message()
    except ai_service.AIUnavailable:
        raise
    except Exception as exc:  # streaming transport / thinking error
        if "thinking" in call_kw and _is_thinking_error(exc):
            retry_kw = {k: v for k, v in call_kw.items() if k != "thinking"}
            if emitted:
                # Already streamed a prefix — re-streaming would double it. Recover
                # via a single non-stream call (the loop reads the returned Message).
                logger.warning("thinking stream failed mid-stream (%s: %s); recovering "
                               "without thinking via non-stream", type(exc).__name__, exc)
                return _create_call(client, retry_kw)
            logger.warning("thinking stream failed (%s: %s); retrying stream without thinking",
                           type(exc).__name__, exc)
            resp = yield from _stream_call(client, retry_kw)
            return resp
        logger.warning("Agent stream failed, falling back to non-stream: %s: %s",
                       type(exc).__name__, exc)
        return _create_call(client, call_kw)


def run_agent(db: Session, company_id, messages: list[dict], project_id=None, user_id=None,
              today: date | None = None, scope: str | None = None,
              extra_context: str = "", draft=None) -> dict:
    """Execute the tool-use loop (non-stream) and return the structured response
    (§3.1) — the long-standing entry point, unchanged for callers/tests.

    Raises ai_service.AIUnavailable if the model cannot be reached or the 60s
    server-side budget is exceeded; callers (api/ai.py) translate that into the
    graceful Turkish degradation response. On success, writes one ai_query_log
    row (§6.1) when user_id is supplied.

    ``today`` (default date.today()) is grounding context for relative date
    phrases; the server — not the model — resolves them to literal ISO dates via
    each tool's ``relative_window`` parameter (§1.2: the model never computes).

    ``scope`` (CR-011-B §2.1) optionally narrows the agent to a domain (gider /
    gelir / finans / hakedis / belge): a preamble + a prioritized tool subset +
    a pre-loaded headline figure. None / unknown = the general agent."""
    final = None
    for ev in _agent_events(db, company_id, messages, project_id, user_id,
                            today or date.today(), stream=False, scope=scope,
                            extra_context=extra_context, draft=draft):
        if ev.get("type") == "final":
            final = ev["data"]
    return final if final is not None else degraded_response()


def run_agent_stream(db: Session, company_id, messages: list[dict], project_id=None,
                     user_id=None, today: date | None = None, scope: str | None = None,
                     extra_context: str = "", draft=None):
    """Streaming variant of run_agent (CR-011-A §1.1): yields delta/step/final
    events for the SSE endpoint. The final event carries the identical structured
    payload as run_agent (charts/citations/log), finalized at stream end.
    ``scope`` (CR-011-B) narrows the agent to a domain as in run_agent.
    ``extra_context`` (CR-035) grounds the answer in a specific saved report."""
    yield from _agent_events(db, company_id, messages, project_id, user_id,
                             today or date.today(), stream=True, scope=scope,
                             extra_context=extra_context, draft=draft)


def sse_event(ev: dict) -> str:
    """Serialize one agent event to a Server-Sent-Events frame (§1.1)."""
    etype = ev.get("type", "message")
    if etype == "final":
        data = ev.get("data", {})
    elif etype == "delta":
        data = {"text": ev.get("text", "")}
    elif etype == "step":
        # PART A/B — pass the cleaned args, narration and thinking through to the
        # client (additive; absent keys default cleanly on the frontend).
        data = {
            "tool": ev.get("tool"), "label": ev.get("label"),
            "input": ev.get("input"), "note": ev.get("note"),
            "thinking": ev.get("thinking"),
        }
    else:
        data = ev
    return f"event: {etype}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _log_query(db: Session, company_id, user_id, messages, tools_used, row_counts):
    """Append one ai_query_log row (§6.1) and return its id (CR-024-A).

    Only the question, tool names and per-tool row counts — never full record
    contents. Never breaks the response: on any logging error returns ``None``.
    """
    from app.models.ai_query_log import AIQueryLog

    question = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    try:
        row = AIQueryLog(
            company_id=company_id, user_id=user_id, question=question,
            tools_used=tools_used, row_counts=row_counts,
        )
        db.add(row)
        db.commit()
        return row.id
    except Exception as exc:  # logging must never fail the request
        logger.warning("ai_query_log write failed: %s", exc)
        db.rollback()
        return None


def degraded_response() -> dict:
    """Graceful response when the model is unavailable (§6.1 — refined in CR-007-E)."""
    return {
        "answer_markdown": DEGRADED_MESSAGE,
        "charts": [],
        "citations": [],
        "tools_used": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "notes": "",
        # CR-024-A: keep the shape consistent with run_agent's success response.
        "query_log_id": None,
        "row_counts": {},
        "proposed_actions": [],
        # CR-011 rich steps (PART A/C): empty defaults keep the payload shape stable.
        "tool_summaries": {},
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
