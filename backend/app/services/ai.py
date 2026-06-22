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
# Distinct from an outage: the API answered but its output couldn't be parsed
# (truncated/JSON malformed/empty extraction) — usually a too-large or oddly
# shaped file, NOT a missing key. Surfaced to the user as a real reason.
AI_RESPONSE_MESSAGE = (
    "AI dosyayı işleyemedi — yanıt beklenen biçimde değildi. Dosya çok büyük veya "
    "düzensiz olabilir; standart içe aktarmayı ya da şablonu deneyin."
)


class AIUnavailable(Exception):
    """The model is unreachable: missing key, SDK missing, or a transport error."""


class AIResponseError(Exception):
    """The model answered but the response could not be parsed/used."""


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


def _call_raw_text(prompt: str, max_tokens: int = 1024) -> str:
    """Run a prompt and return the model's raw text. Raises AIUnavailable ONLY for
    a true outage (missing key / SDK / transport error) — JSON parsing is the
    caller's job, so a parse failure is never masked as 'AI unavailable'."""
    client = _client()
    try:
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
    except AIUnavailable:
        raise
    except Exception as exc:  # network, TLS, rate limit, auth, etc.
        # Log the exception type + message so SSL/cert, auth, and rate-limit
        # failures are distinguishable in the logs.
        logger.warning("Claude API call failed: %s: %s", type(exc).__name__, exc)
        raise AIUnavailable(AI_UNAVAILABLE_MESSAGE) from exc


def _call_json(prompt: str, max_tokens: int = 1024) -> dict | list:
    """Single-shot prompt expecting JSON. A transport failure raises AIUnavailable;
    a JSON parse failure is also folded into AIUnavailable here for the legacy
    callers (alerts/narrative) that only handle that. The import path uses
    _call_raw_text directly so it can tell the two apart (CR-015-fix)."""
    text = _call_raw_text(prompt, max_tokens=max_tokens)
    try:
        return _extract_json(text)
    except Exception as exc:
        logger.warning("Claude JSON parse failed: %s: %s", type(exc).__name__, exc)
        raise AIUnavailable(AI_UNAVAILABLE_MESSAGE) from exc


def _extract_json(text: str):
    """Pull the first complete JSON object/array out of a model response.

    Balances braces/brackets (string-aware) so nested JSON is extracted intact and
    a truncated response is detected rather than silently mis-parsed. Raises
    ValueError on no-JSON / incomplete-JSON; callers decide how to surface it.
    """
    text = text.strip()
    if text.startswith("```"):
        # Strip a leading ```json fence (and the trailing fence if present).
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.lstrip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    if start == -1:
        raise ValueError("Yanıtta JSON bulunamadı")
    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    end = -1
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise ValueError("JSON tamamlanmamış — yanıt kesilmiş olabilir")
    return json.loads(text[start:end])


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
        '"recommended_action": "...", "severity": "high|medium|low", '
        '"impact_try": <bu eylemin tahmini finansal etkisi/tasarrufu, yalnızca '
        'verilerden makul biçimde tahmin edilebiliyorsa sayı (TRY); aksi halde bu '
        'alanı hiç ekleme>, "impact_label": "<etkinin kısa açıklaması, opsiyonel>"}]. '
        "Veriler: " + payload
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


def project_narrative(summary: dict) -> str:
    """CR-003-F: a 2-3 sentence Turkish project summary (biggest positive/negative
    driver, cash risk, next step). Degrades gracefully without the API."""
    payload = json.dumps(summary, default=_decimal_default, ensure_ascii=False)
    prompt = (
        "Sen bir inşaat proje finansal analistisin. Aşağıdaki proje verilerine göre "
        "2-3 cümlelik kısa bir Türkçe özet yaz: en büyük olumlu etken, en büyük "
        "olumsuz etken, nakit riski ve önerilen sonraki adım. Yalnızca düz metin "
        "döndür, JSON değil. Veriler: " + payload
    )
    try:
        client = _client()
        msg = client.messages.create(
            model=settings.anthropic_model, max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except Exception:
        # Deterministic fallback.
        margin = float(summary.get("forecast_final_margin_pct", summary.get("margin_pct", 0)))
        cash = float(summary.get("net_cash_position_try", 0))
        parts = []
        if margin < 5:
            parts.append(f"Tahmini final kar marjı %{margin:.1f} ile kritik seviyede; acil maliyet kontrolü gerekiyor.")
        elif margin < 10:
            parts.append(f"Tahmini final kar marjı %{margin:.1f} ile hedefin altında.")
        else:
            parts.append(f"Tahmini final kar marjı %{margin:.1f} ile sağlıklı görünüyor.")
        if cash < 0:
            parts.append(f"Nakit pozisyonu negatif ({cash:,.0f}₺); tahsilatların hızlandırılması önerilir.")
        else:
            parts.append("Nakit pozisyonu pozitif.")
        parts.append("Bütçe sapması olan kategoriler gözden geçirilmelidir.")
        return " ".join(parts)


ASSISTANT_SYSTEM = (
    "Sen bir Türk inşaat şirketinin AI finansal asistanısın. Yalnızca verilen proje "
    "finansal verilerine dayanarak Türkçe yanıt ver. Sayısal değerleri Türkçe formatta "
    "(₺, %) ver. Belirsiz verilere dayanarak tahmin yapma — yalnızca bilinen verileri kullan.\n"
    # CR-004-I: response formatting rules.
    "Yanıt biçimi:\n"
    "- Yanıtı madde madde formatla; her noktayı ayrı satırda yaz.\n"
    "- Önemli rakamları markdown ile kalın yap (**değer** biçiminde).\n"
    "- Yanıtın sonunda hangi projeyi veya veriyi baz aldığını belirt.\n"
    "- En fazla 300 kelime kullan — özlü tut."
)


def assistant_answer(question: str, context: dict) -> str:
    """CR-003-H: answer a natural-language financial question from project data."""
    payload = json.dumps(context, default=_decimal_default, ensure_ascii=False)
    try:
        client = _client()
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1000,
            system=ASSISTANT_SYSTEM,
            messages=[{"role": "user", "content": f"Veriler:\n{payload}\n\nSoru: {question}"}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except AIUnavailable:
        return (
            "AI şu an kullanılamıyor. Sorunuzu yanıtlamak için yapay zeka servisi "
            "gereklidir. Lütfen daha sonra tekrar deneyin."
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("assistant_answer failed: %s", exc)
        return "AI şu an kullanılamıyor. Lütfen daha sonra tekrar deneyin."


def _plain_text(prompt: str, max_tokens: int = 600) -> str:
    client = _client()
    msg = client.messages.create(
        model=settings.anthropic_model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


def management_summary(context: dict) -> str:
    """CR-003-K: 1-page Turkish executive summary (3 başarı, 3 risk, 3 eylem)."""
    payload = json.dumps(context, default=_decimal_default, ensure_ascii=False)
    try:
        return _plain_text(
            "Sen bir Türk inşaat şirketi için yönetim kurulu raporu yazıyorsun. "
            "Aşağıdaki verilere göre 1 paragraflık Türkçe yönetici özeti yaz: en önemli "
            "3 başarı, en önemli 3 risk ve önerilen 3 eylem. Veriler: " + payload, 800
        )
    except Exception:
        return (
            f"{context.get('sirket', 'Şirket')} portföyünde {context.get('proje_sayisi', 0)} aktif proje "
            f"bulunmaktadır. Toplam sözleşme değeri {context.get('toplam_sozlesme', '0')}₺, bekleyen "
            f"tahsilat {context.get('toplam_bekleyen_tahsilat', '0')}₺'dir. Öncelikli eylem: vadesi geçmiş "
            "tahsilatların takibi ve bütçe aşımı olan kategorilerin gözden geçirilmesidir."
        )


def management_actions(context: dict) -> str:
    """CR-003-K: prioritised action list (Turkish)."""
    payload = json.dumps(context, default=_decimal_default, ensure_ascii=False)
    try:
        return _plain_text(
            "Aşağıdaki proje portföyü için öncelikli eylem listesi yaz (madde madde, "
            "Türkçe). Veriler: " + payload, 600
        )
    except Exception:
        return (
            "1. Vadesi geçmiş hakedişleri takip edin.\n"
            "2. Bütçe aşımı olan kategorileri inceleyin.\n"
            "3. Onay bekleyen işlemleri sonuçlandırın.\n"
            "4. Nakit açığı riski olan projeler için tahsilatı hızlandırın."
        )


def build_import_prompt(excel_text: str) -> str:
    """Prompt for the AI Excel importer (extracted so it is testable)."""
    from app.constants import COST_CATEGORY_KEYS

    return (
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
        # CR-003-B: distinguish supplier invoices (costs) from client invoices (revenue).
        "ÖNEMLİ: Tedarikçi faturası (supplier invoice) ile işverene kesilen fatura "
        "(client invoice/hakediş) arasındaki farkı dikkate al. Tedarikçi faturası = "
        "maliyet_girisleri. İşverene kesilen fatura/hakediş = faturalar. Fatura numarası "
        "olması bir kaydı otomatik olarak faturalar kategorisine sokmaz.\n\n"
        f"Excel verisi:\n{excel_text}"
    )


def analyze_excel_import(excel_text: str) -> dict:
    """CR-002-H: classify messy Excel content into structured records.

    Returns a dict with keys maliyet_girisleri / faturalar / alt_yukleniciler /
    ekipman / tanimsiz, each a list of records carrying a 'confidence' (0..1).
    Retries JSON parsing up to 2 times; raises AIUnavailable on failure.
    """
    prompt = build_import_prompt(excel_text)
    # Transport/outage -> AIUnavailable (propagates). Parse/format -> AIResponseError
    # so the endpoint surfaces a REAL reason instead of "AI unavailable" (CR-015-fix).
    text = _call_raw_text(prompt, max_tokens=8000)
    try:
        result = _extract_json(text)
    except Exception as exc:
        logger.warning("AI import JSON parse failed: %s: %s", type(exc).__name__, exc)
        raise AIResponseError(AI_RESPONSE_MESSAGE) from exc
    if not isinstance(result, dict):
        logger.warning("AI import returned non-object JSON: %s", type(result).__name__)
        raise AIResponseError(AI_RESPONSE_MESSAGE)
    for key in ("maliyet_girisleri", "faturalar", "alt_yukleniciler", "ekipman", "tanimsiz"):
        result.setdefault(key, [])
    return result


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


def analyze_document_image(data: bytes, content_type: str) -> dict:
    """Track A: vision extraction for a supplier-invoice photo or PDF.

    Accepts JPEG/PNG photos (phone camera) and PDF. Returns supplier-invoice
    fields plus a suggested cost_category (one of the standard keys) and an
    overall confidence (0..1). Never writes to the DB — the user confirms.
    """
    import base64

    from app.constants import COST_CATEGORY_KEYS

    client = _client()
    b64 = base64.standard_b64encode(data).decode("ascii")
    if content_type == "application/pdf":
        source_block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    elif content_type in ("image/jpeg", "image/png"):
        source_block = {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}}
    else:
        raise AIUnavailable(AI_UNAVAILABLE_MESSAGE)

    categories = ", ".join(COST_CATEGORY_KEYS)
    prompt = (
        "Bu bir tedarikçi/malzeme faturasının fotoğrafı veya PDF'idir (Türkçe olabilir). "
        "Faturadaki bilgileri çıkar ve SADECE şu JSON nesnesini döndür:\n"
        '{"supplier_name": "...", "invoice_number": "...", "invoice_date": "YYYY-MM-DD", '
        '"amount_try": 0.00, "vat_rate": 20, "description": "kısa açıklama", '
        '"cost_category": "<anahtar>", "confidence": 0.0}\n'
        "Kurallar: amount_try KDV HARİÇ matrah tutarıdır (sayı, ondalık ayırıcı nokta). "
        "vat_rate yüzde olarak KDV oranıdır (örn. 20). "
        f"cost_category şu anahtarlardan faturaya EN UYGUN olanı olmalı: {categories}. "
        "confidence 0 ile 1 arası genel güven skorudur. "
        "Bir alanı okuyamazsan o alan için null döndür. JSON dışında hiçbir şey yazma."
    )
    last_err: Exception | None = None
    for _ in range(2):  # retry JSON parsing
        try:
            msg = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=1024,
                messages=[{"role": "user", "content": [source_block, {"type": "text", "text": prompt}]}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            result = _extract_json(text)
            if isinstance(result, dict):
                return result
        except AIUnavailable:
            raise
        except Exception as exc:  # JSON parse / API error -> retry
            last_err = exc
    logger.warning("Document image extraction failed: %s", last_err)
    raise AIUnavailable(AI_UNAVAILABLE_MESSAGE)


def analyze_document_smart(data: bytes, content_type: str, context: dict) -> dict:
    """Smart capture: rich invoice extraction + context-grounded project & cost-code
    suggestion with reasoning. The AI is given supplier history, the active project
    list with their budget categories, and the cost-category descriptions, so it can
    suggest WHERE the cost belongs and explain WHY. Never writes — the user confirms.

    Returns a dict with: supplier_name, invoice_number, invoice_date, due_date,
    currency, subtotal, vat_amount, vat_rate, total, line_items[], confidence,
    suggested_project_id, suggested_cost_category, reasoning.
    """
    import base64

    from app.constants import COST_CATEGORY_KEYS

    client = _client()
    b64 = base64.standard_b64encode(data).decode("ascii")
    if content_type == "application/pdf":
        source_block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    elif content_type in ("image/jpeg", "image/png"):
        source_block = {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}}
    else:
        raise AIUnavailable(AI_UNAVAILABLE_MESSAGE)

    ctx = json.dumps(context, ensure_ascii=False, default=_decimal_default)
    categories = ", ".join(COST_CATEGORY_KEYS)
    schema = (
        '{"supplier_name": "...", "invoice_number": "...", "invoice_date": "YYYY-MM-DD", '
        '"due_date": "YYYY-MM-DD", "currency": "TRY", "subtotal": 0.00, "vat_amount": 0.00, '
        '"vat_rate": 20, "total": 0.00, '
        '"line_items": [{"description": "...", "quantity": 0, "unit_price": 0.00, "amount": 0.00}], '
        '"confidence": 0.0, "suggested_project_id": "<id|null>", '
        '"suggested_cost_category": "<anahtar>", "reasoning": "..."}'
    )
    prompt = (
        "Bu bir tedarikçi/malzeme faturasının görüntüsü veya PDF'idir (genellikle Türkçe). "
        "İki görevi yap:\n"
        "1) Fatura alanlarını ve TÜM satır kalemlerini eksiksiz çıkar.\n"
        "2) Bu faturanın HANGİ projeye ve HANGİ maliyet kategorisine ait olduğunu, sana verilen "
        "BAĞLAM'ı (tedarikçi geçmişi ve daha önce onaylanmış sınıflandırmalar, aktif proje listesi "
        "ve her projenin bütçe kategorileri, kategori açıklamaları) kullanarak öner.\n\n"
        "SADECE şu JSON nesnesini döndür:\n" + schema + "\n\n"
        "Kurallar:\n"
        "- subtotal KDV hariç matrah, vat_amount KDV tutarı, total KDV dahil genel toplam "
        "(sayı, ondalık ayırıcı nokta).\n"
        "- vat_rate yüzde (örn. 20). currency ISO para birimi kodu (TRY, EUR, USD...).\n"
        "- invoice_date ve due_date MUTLAKA YYYY-MM-DD biçiminde olmalı (örn. 2026-06-15), "
        "Türkçe gün.ay.yıl biçimini bu biçime çevir. Fatura açık bir son ödeme/vade tarihi "
        "göstermiyorsa ama '30 gün vade', 'net 30' gibi bir ödeme vadesi belirtiyorsa "
        "due_date = invoice_date + o gün sayısı olarak hesapla. Hiç bilgi yoksa null.\n"
        "- line_items faturadaki her satır kalemini içersin (yoksa boş dizi).\n"
        f"- suggested_cost_category şu anahtarlardan biri olmalı: {categories}.\n"
        "- suggested_project_id BAĞLAM'daki projelerden birinin id'si olmalı; uygun proje yoksa null.\n"
        "- reasoning Türkçe olmalı ve seçimini AÇIKLA: tedarikçinin geçmiş kullanımına, satır "
        "kalemlerine, projelerin bütçe kategorilerine ve kategori açıklamalarına atıfta bulun.\n"
        "- confidence 0 ile 1 arası genel güven skoru. Okuyamadığın alan için null döndür.\n"
        "- JSON dışında hiçbir şey yazma.\n\n"
        "BAĞLAM:\n" + ctx
    )
    last_err: Exception | None = None
    for _ in range(2):
        try:
            msg = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=2500,
                messages=[{"role": "user", "content": [source_block, {"type": "text", "text": prompt}]}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            result = _extract_json(text)
            if isinstance(result, dict):
                return result
        except AIUnavailable:
            raise
        except Exception as exc:  # JSON parse / API error -> retry
            last_err = exc
    logger.warning("Smart document extraction failed: %s", last_err)
    raise AIUnavailable(AI_UNAVAILABLE_MESSAGE)


def analyze_and_classify(data: bytes, content_type: str, context: dict) -> dict:
    """CR-012 Template A: classify a document's TYPE and route it to a destination.

    Builds on the smart-capture extraction but adds a routing decision so the
    auto-file automation can propose WHERE the document belongs. v1 routes a
    realistic subset:

    - ``supplier_invoice`` (tedarikçi/malzeme faturası)  -> ``cost`` (Gider)
    - ``client_invoice``   (kestiğimiz hakediş/müşteri faturası) -> ``client_invoice``
    - anything else / uncertain -> ``destination=None`` (caller falls back to the
      manual review preview; no approval is auto-created).

    Returns ``{doc_type, destination, confidence, project_guess, fields}`` where
    ``fields`` is shaped for the chosen destination. Never writes to the DB.
    """
    import base64

    from app.constants import COST_CATEGORY_KEYS

    client = _client()
    b64 = base64.standard_b64encode(data).decode("ascii")
    if content_type == "application/pdf":
        source_block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    elif content_type in ("image/jpeg", "image/png"):
        source_block = {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}}
    else:
        raise AIUnavailable(AI_UNAVAILABLE_MESSAGE)

    ctx = json.dumps(context, ensure_ascii=False, default=_decimal_default)
    categories = ", ".join(COST_CATEGORY_KEYS)
    schema = (
        '{"doc_type": "supplier_invoice|client_invoice|other", '
        '"destination": "cost|client_invoice|null", "confidence": 0.0, '
        '"project_guess": "<id|null>", '
        '"fields": {"supplier_name": "...", "invoice_number": "...", '
        '"invoice_date": "YYYY-MM-DD", "due_date": "YYYY-MM-DD", '
        '"amount_try": 0.00, "vat_rate": 20, "retention_amount_try": 0.00, '
        '"cost_category": "<anahtar>", "description": "..."}}'
    )
    prompt = (
        "Bu bir belgenin görüntüsü veya PDF'idir (genellikle Türkçe). İki görevi yap:\n"
        "1) Belgenin TÜRÜNÜ belirle:\n"
        "   - 'supplier_invoice': bir tedarikçiden/maliyetten gelen ALIŞ faturası (gider).\n"
        "   - 'client_invoice': işverene/müşteriye KESİLEN hakediş veya satış faturası (gelir).\n"
        "   - 'other': fatura olmayan veya belirsiz belge.\n"
        "2) Alanları çıkar ve aşağıdaki hedefe yönlendir:\n"
        "   - supplier_invoice -> destination='cost'\n"
        "   - client_invoice  -> destination='client_invoice'\n"
        "   - other/belirsiz   -> destination=null\n\n"
        "SADECE şu JSON nesnesini döndür:\n" + schema + "\n\n"
        "Kurallar:\n"
        "- amount_try KDV HARİÇ matrah tutarıdır (sayı, ondalık ayırıcı nokta). vat_rate yüzde (örn. 20).\n"
        "- invoice_date ve due_date MUTLAKA YYYY-MM-DD biçiminde olmalı; bilinmiyorsa null.\n"
        f"- cost_category yalnızca destination='cost' için ve şu anahtarlardan biri olmalı: {categories}.\n"
        "- retention_amount_try yalnızca destination='client_invoice' için anlamlıdır (hakediş kesintisi); yoksa 0.\n"
        "- project_guess BAĞLAM'daki projelerden birinin id'si olmalı; uygun proje yoksa null.\n"
        "- confidence 0 ile 1 arası genel güven skorudur; tür VE alanlardan ne kadar emin olduğunu yansıtsın.\n"
        "- JSON dışında hiçbir şey yazma.\n\n"
        "BAĞLAM:\n" + ctx
    )
    last_err: Exception | None = None
    for _ in range(2):
        try:
            msg = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=1500,
                messages=[{"role": "user", "content": [source_block, {"type": "text", "text": prompt}]}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            result = _extract_json(text)
            if isinstance(result, dict):
                return result
        except AIUnavailable:
            raise
        except Exception as exc:  # JSON parse / API error -> retry
            last_err = exc
    logger.warning("Document classify failed: %s", last_err)
    raise AIUnavailable(AI_UNAVAILABLE_MESSAGE)
