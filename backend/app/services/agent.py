"""CR-007-B — Agentic tool-use loop (orchestration).

Mirrors the existing services/ai.py vs api/ai.py split: this module orchestrates
the Anthropic tool-use loop; the read-only data lives in services/agent_tools.py.

Governing principle (§1.2): the model never computes numbers — it only calls the
fixed, read-only tools (which compute via SQL) and narrates the results. There is
no raw-SQL tool, and ``company_id`` is injected here from the authenticated user,
never taken from tool input.
"""
import json
import logging
import time
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.constants import COST_CATEGORIES
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


def _date_grounding(today: date) -> str:
    """Today's server date, appended to the system prompt so relative-time phrases
    resolve to the correct year. The model must COPY literal ISO dates derived from
    this context into date_from/date_to — it must not invent a year (§1.2)."""
    return (
        f"\n\nBUGÜN: {today:%Y-%m-%d}. Göreli tarih ifadelerini (son 6 ay, bu yıl, "
        "geçen ay, son çeyrek, geçen yıl) DAİMA bu tarihe göre hesapla; yılı asla "
        "tahmin etme. Araçlara verdiğin date_from/date_to değerleri, bu BUGÜN "
        "bilgisinden türetilmiş birebir ISO tarihleri (YYYY-MM-DD) olmalı."
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
}


def build_tool_schemas() -> list[dict]:
    """Anthropic tool definitions — one per read-only tool plus create_chart.
    No input_schema contains a company_id field (§1.2 #4)."""
    group_by_cost = {"type": "string", "enum": ["month", "category", "supplier", "project"]}
    group_by_inv = {"type": "string", "enum": ["month", "type", "status", "project"]}
    date_s = {"type": "string", "description": "YYYY-MM-DD"}
    pid = {"type": "string", "description": "Proje UUID"}

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
            }, "required": ["vendor_name"]},
        },
        {
            "name": "compare_vendors",
            "description": "Bir dönemde tedarikçi başına toplam harcamayı sıralı (en yüksekten) döndürür.",
            "input_schema": {"type": "object", "properties": {
                "date_from": date_s, "date_to": date_s,
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


def execute_tool(db: Session, company_id, name: str, tool_input: dict,
                 charts: list, citations: list, seen: set) -> dict:
    """Run one tool with company_id injected server-side. Never raises — returns
    an error dict so the model can recover within the loop."""
    if name == "create_chart":
        try:
            spec = tools.create_chart(**(tool_input or {}))
        except tools.ToolError as exc:
            return {"error": str(exc)}
        charts.append(spec)
        return {"ok": True, "chart": spec}

    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return {"error": f"Bilinmeyen araç: {name}"}
    func, allowed = entry
    params = _coerce_params(allowed, tool_input)
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


def run_agent(db: Session, company_id, messages: list[dict], project_id=None, user_id=None,
              today: date | None = None) -> dict:
    """Execute the tool-use loop and return the structured response (§3.1).

    Raises ai_service.AIUnavailable if the model cannot be reached or the 60s
    server-side budget is exceeded; callers (api/ai.py) translate that into the
    graceful Turkish degradation response. On success, writes one ai_query_log
    row (§6.1) when user_id is supplied.

    ``today`` (default date.today()) grounds relative date phrases ("son 6 ay",
    "bu yıl") so the model resolves them against the real server date instead of
    guessing a year. Injected, not computed — the model copies literal ISO dates
    from this context into tool params (§1.2: the model never computes).
    """
    client = ai_service._client()  # raises AIUnavailable when no key/SDK
    tool_schemas = build_tool_schemas()

    system = SYSTEM_PROMPT + _date_grounding(today or date.today())
    if project_id is not None:
        system += f"\n\nAKTİF PROJE BAĞLAMI: Kullanıcı şu an proje {project_id} bağlamında çalışıyor. Aksi belirtilmedikçe bu projeyi varsay."

    convo: list[dict] = [{"role": m["role"], "content": m["content"]} for m in messages]
    tools_used: list[str] = []
    row_counts: dict[str, int] = {}
    charts: list[dict] = []
    citations: list[dict] = []
    seen_citation_ids: set = set()

    timeout = settings.ai_agent_timeout_seconds
    started = time.monotonic()

    resp = None
    for i in range(MAX_ITERATIONS):
        # 60s server-side budget across the whole loop (§6.1).
        if time.monotonic() - started > timeout:
            logger.warning("Agent loop exceeded %ss budget", timeout)
            raise ai_service.AIUnavailable("timeout")

        force_final = i == MAX_ITERATIONS - 1
        try:
            resp = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=settings.ai_agent_max_tokens,
                system=system,
                tools=tool_schemas,
                tool_choice={"type": "none"} if force_final else {"type": "auto"},
                messages=convo,
                timeout=timeout,
            )
        except ai_service.AIUnavailable:
            raise
        except Exception as exc:  # network / timeout / API error -> degrade
            logger.warning("Agent Claude call failed: %s: %s", type(exc).__name__, exc)
            raise ai_service.AIUnavailable("Claude error") from exc

        if resp.stop_reason != "tool_use":
            break

        # Append the assistant tool_use turn, then the tool_result turn.
        convo.append({"role": "assistant", "content": resp.content})
        results_block = []
        for block in resp.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            tools_used.append(block.name)
            result = execute_tool(db, company_id, block.name, dict(block.input or {}),
                                  charts, citations, seen_citation_ids)
            if isinstance(result, dict) and "row_count" in result:
                row_counts[block.name] = row_counts.get(block.name, 0) + int(result["row_count"])
            results_block.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })
        convo.append({"role": "user", "content": results_block})

    answer = _text_of(resp.content) if resp is not None else ""

    # CR-024-A: capture the log row id so the answer can be linked to feedback.
    query_log_id = None
    if user_id is not None:
        query_log_id = _log_query(db, company_id, user_id, messages, tools_used, row_counts)

    return {
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
    }


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
    }
