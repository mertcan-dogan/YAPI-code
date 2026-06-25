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
}

# CR-011-C — ACTION tools (propose-only). Kept in a SEPARATE registry so the
# read-only guarantee on TOOL_REGISTRY stays intact and the executor routes
# actions through the approvals lifecycle (never a direct mutation, §0.2.1).
ACTION_TOOL_REGISTRY = {
    "propose_reminder": (actions.propose_reminder, {"title", "note", "due_date", "project_id"}),
    "propose_flag_invoice": (actions.propose_flag_invoice,
                             {"target_kind", "target_id", "reason", "project_id"}),
    "propose_followup_task": (actions.propose_followup_task, {"title", "note", "project_id"}),
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

    return [
        {
            "name": "list_projects",
            "description": "Şirketin tüm projelerinin portföy özetini döndürür (durum filtresi opsiyonel).",
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
ALWAYS_SCOPED_TOOLS = {"create_chart", "list_projects"}

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
}


def _step_label(name: str) -> str:
    return _STEP_LABELS.get(name, "Veriler inceleniyor…")


# CR-011-C — propose-only action guidance (always present; the agent has action
# tools in every scope). Reinforces the §0.2.1 invariant in the model's own words.
_ACTION_GUIDANCE = (
    "\n\nEYLEM ARAÇLARI (propose_reminder, propose_flag_invoice, propose_followup_task): "
    "Bu araçlar HİÇBİR ŞEYİ DOĞRUDAN DEĞİŞTİRMEZ — yalnızca ONAY BEKLEYEN bir öneri "
    "oluştururlar; değişiklik ancak kullanıcı /approvals sayfasından onaylarsa uygulanır.\n"
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
    "Birden fazla eylem istenirse her biri için AYRI bir araç çağrısı yap.\n"
    "NE ZAMAN ÇAĞIRMAMALISIN: Kullanıcı yalnızca GENEL TAVSİYE veya bir öneri/yapılacaklar "
    "LİSTESİ isterse (örn. 'ne yapmalıyım', 'önerilerin neler') eylem aracı çağırma; "
    "serbest metinle yanıtla.\n"
    "Sonucu bildirirken ASLA 'yaptım/oluşturdum/işaretledim' deme; 'öneri oluşturuldu, "
    "onayınızı bekliyor' de ve onay için /approvals sayfasına yönlendir."
)


def _build_system(today: date | None, project_id, scope: str | None = None,
                  scope_context: str = "") -> str:
    """Assemble the system prompt: base + server-date rules + action guidance +
    optional domain `scope` preamble + cheap pre-loaded scope context + active
    project (§2.1, §3.1)."""
    system = SYSTEM_PROMPT + _date_guidance(today or date.today()) + _ACTION_GUIDANCE
    pre = _scope_preamble(scope)
    if pre:
        system += "\n\nALAN ODAĞI: " + pre
    if scope_context:
        system += "\n\nALAN BAĞLAMI (ön-yükleme): " + scope_context
    if project_id is not None:
        system += (
            f"\n\nAKTİF PROJE BAĞLAMI: Kullanıcı şu an proje {project_id} bağlamında "
            "çalışıyor. Aksi belirtilmedikçe bu projeyi varsay."
        )
    return system


def _agent_events(db: Session, company_id, messages: list[dict], project_id, user_id,
                  today: date, stream: bool, scope: str | None = None):
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
    system = _build_system(today, project_id, scope, scope_ctx)

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
              today: date | None = None, scope: str | None = None) -> dict:
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
                            today or date.today(), stream=False, scope=scope):
        if ev.get("type") == "final":
            final = ev["data"]
    return final if final is not None else degraded_response()


def run_agent_stream(db: Session, company_id, messages: list[dict], project_id=None,
                     user_id=None, today: date | None = None, scope: str | None = None):
    """Streaming variant of run_agent (CR-011-A §1.1): yields delta/step/final
    events for the SSE endpoint. The final event carries the identical structured
    payload as run_agent (charts/citations/log), finalized at stream end.
    ``scope`` (CR-011-B) narrows the agent to a domain as in run_agent."""
    yield from _agent_events(db, company_id, messages, project_id, user_id,
                             today or date.today(), stream=True, scope=scope)


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
