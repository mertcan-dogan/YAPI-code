"""Claude AI integration (Section 5).

All prompts and outputs are Turkish. AI never writes to the database — it only
produces suggestions/alerts that a user confirms. If the API key is missing or
the call fails, every function degrades gracefully (Section 5.5).
"""
import json
import logging
from decimal import Decimal
from typing import Any

from app.config import settings

logger = logging.getLogger("yapi.ai")

AI_UNAVAILABLE_MESSAGE = "AI şu an kullanılamıyor"


class AIUnavailable(Exception):
    pass


def _client():
    if not settings.anthropic_api_key:
        raise AIUnavailable(AI_UNAVAILABLE_MESSAGE)
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise AIUnavailable(AI_UNAVAILABLE_MESSAGE) from exc
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def is_available() -> bool:
    return bool(settings.anthropic_api_key)


def _decimal_default(o: Any):
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


def _call_json(prompt: str, max_tokens: int = 1024) -> dict | list:
    """Single-shot prompt expecting a JSON response. Raises AIUnavailable on failure."""
    client = _client()
    try:
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
        return _extract_json(text)
    except AIUnavailable:
        raise
    except Exception as exc:  # network, rate limit, etc.
        logger.warning("Claude API call failed: %s", exc)
        raise AIUnavailable(AI_UNAVAILABLE_MESSAGE) from exc


def _extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    if start == -1:
        raise AIUnavailable(AI_UNAVAILABLE_MESSAGE)
    return json.loads(text[start:].rsplit("}", 1)[0] + "}" if text[start] == "{" else text[start:])


# --- Alert Engine (Section 5.2) ---
def analyze_margin(financials: dict) -> dict | None:
    """Alert Type 1: margin warning. Returns alert dict or None if no risk."""
    margin = float(financials.get("margin_pct", 0))
    target = financials.get("target_margin_pct")
    target = float(target) if target is not None else None
    triggered = margin < 10 or (target is not None and margin < target)
    if not triggered:
        return None

    payload = json.dumps(financials, default=_decimal_default, ensure_ascii=False)
    prompt = (
        "Sen bir inşaat proje finansal analisti olarak görev yapıyorsun. Aşağıdaki "
        "proje verilerini analiz et ve kar marjı riskini Türkçe olarak açıkla. "
        'Yanıtın JSON formatında olsun: {"title": "...", "body": "...", '
        '"severity": "high|medium|low", "recommended_action": "..."}. Veriler: '
        + payload
    )
    try:
        result = _call_json(prompt)
    except AIUnavailable:
        # Deterministic fallback so an alert still surfaces without the API.
        severity = "high" if margin < 5 else "medium"
        return {
            "alert_type": "margin_warning",
            "severity": severity,
            "title": "Kar Marjı Uyarısı",
            "body": f"Güncel kar marjı %{margin:.1f}. Hedefin altında, maliyet kontrolü gerekli.",
            "recommended_action": "Maliyet kalemlerini ve final tahminlerini gözden geçirin.",
        }
    result["alert_type"] = "margin_warning"
    return result


def daily_briefing(projects_summary: list[dict]) -> list[dict]:
    """'Bugün Ne Yapmalısın' — up to 8 prioritised Turkish action items (Section 5.4)."""
    if not projects_summary:
        return []
    payload = json.dumps(projects_summary, default=_decimal_default, ensure_ascii=False)
    prompt = (
        "Sen bir inşaat şirketi için finansal asistansın. Aşağıdaki aktif projelerin "
        "özetini incele ve yöneticinin bugün dikkat etmesi gereken en fazla 8 maddeyi "
        "öncelik sırasına göre Türkçe olarak listele. Yanıt JSON dizisi olsun: "
        '[{"priority": 1, "project_name": "...", "issue": "...", '
        '"recommended_action": "...", "severity": "high|medium|low"}]. Veriler: ' + payload
    )
    try:
        result = _call_json(prompt, max_tokens=1500)
        if isinstance(result, list):
            return result[:8]
        return []
    except AIUnavailable:
        # Fallback: derive priorities from RAG status without the API.
        items = []
        for p in sorted(projects_summary, key=lambda x: x.get("margin_pct", 100)):
            if p.get("rag_status") in ("red", "amber"):
                items.append(
                    {
                        "priority": len(items) + 1,
                        "project_name": p.get("name", ""),
                        "issue": p.get("rag_reason_tr", "Dikkat gerektiriyor"),
                        "recommended_action": "Proje finansallarını gözden geçirin.",
                        "severity": "high" if p.get("rag_status") == "red" else "medium",
                    }
                )
            if len(items) >= 8:
                break
        return items


def analyze_excel_import(excel_text: str) -> dict:
    """CR-002-H: classify messy Excel content into structured records.

    Returns a dict with keys maliyet_girisleri / faturalar / alt_yukleniciler /
    ekipman / tanimsiz, each a list of records carrying a 'confidence' (0..1).
    Retries JSON parsing up to 2 times; raises AIUnavailable on failure.
    """
    from app.constants import COST_CATEGORY_KEYS

    prompt = (
        "Sen bir Türk inşaat projesi finans uzmanısın. Aşağıdaki Excel verilerini "
        "analiz et ve YALNIZCA JSON formatında döndür. Verileri şu kategorilere ayır "
        "ve her kayıt için 0-1 arası 'confidence' (güven) skoru ekle. Eksik alanları "
        "null bırak.\n\n"
        "JSON şeması:\n"
        "{\n"
        '  "maliyet_girisleri": [{"entry_date":"YYYY-MM-DD","cost_category":"<key>",'
        '"supplier_name":"...","description":"...","amount_try":0,"vat_rate":20,'
        '"payment_due_date":"YYYY-MM-DD|null","payment_status":"unpaid|paid","confidence":0.0}],\n'
        '  "faturalar": [{"invoice_number":"...","invoice_date":"YYYY-MM-DD","amount_try":0,'
        '"vat_rate":20,"due_date":"YYYY-MM-DD","confidence":0.0}],\n'
        '  "alt_yukleniciler": [{"name":"...","scope_of_work":"...","contract_value_try":0,"confidence":0.0}],\n'
        '  "ekipman": [{"equipment_name":"...","ownership_type":"rented|owned","rate_try":0,'
        '"rate_unit":"day|month","deployment_start":"YYYY-MM-DD","confidence":0.0}],\n'
        '  "tanimsiz": [{"raw":"...","confidence":0.0}]\n'
        "}\n\n"
        f"cost_category şu anahtarlardan biri olmalı: {', '.join(COST_CATEGORY_KEYS)}.\n\n"
        f"Excel verisi:\n{excel_text}"
    )
    last_err: Exception | None = None
    for _ in range(2):  # retry JSON parsing up to 2 times
        try:
            result = _call_json(prompt, max_tokens=4000)
            if isinstance(result, dict):
                # Ensure all expected keys exist.
                for key in ("maliyet_girisleri", "faturalar", "alt_yukleniciler", "ekipman", "tanimsiz"):
                    result.setdefault(key, [])
                return result
        except AIUnavailable as exc:
            raise
        except Exception as exc:  # JSON parse error -> retry
            last_err = exc
    logger.warning("AI import JSON parse failed: %s", last_err)
    raise AIUnavailable(AI_UNAVAILABLE_MESSAGE)


def extract_invoice(pdf_bytes: bytes) -> dict:
    """PDF invoice field extraction (Section 5.3). Returns extracted fields."""
    import base64

    client = _client()
    b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
    prompt = (
        "Bu bir tedarikçi faturasının PDF'idir. Faturadan şu alanları çıkar ve JSON "
        'formatında döndür: {"supplier_name": "...", "invoice_number": "...", '
        '"invoice_date": "YYYY-MM-DD", "amount_try": 0.00, "vat_rate": 20, '
        '"vat_amount": 0.00, "total_with_vat": 0.00, "description": "..."}. '
        "Eğer bir alanı bulamazsan null döndür."
    )
    try:
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return _extract_json(text)
    except AIUnavailable:
        raise
    except Exception as exc:
        logger.warning("Invoice extraction failed: %s", exc)
        raise AIUnavailable(AI_UNAVAILABLE_MESSAGE) from exc
