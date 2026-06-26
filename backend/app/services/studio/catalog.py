"""CR-032 §3 — the semantic catalog: dimension + metric registries.

Two ordered registries describe everything the studio engine can chart. Each
entry carries:

* PUBLIC fields — ``label`` (Turkish), ``type``, ``group``, ``description``,
  ``status`` — exposed by ``GET /studio/catalog`` and drives the CR-033 picker.
* INTERNAL fields — ``grain``/``grains``/``dual``/``basis`` — the engine's
  resolution map. NEVER serialized (``get_catalog_public`` whitelists the public
  keys, so the internal mapping cannot leak even if a key is added later).

§3.3 governs v1 scope (AUTHORITATIVE):
* every entry has ``status`` ∈ {"available", "coming_soon"}. The catalog returns
  BOTH (coming_soon is badged "Yakında"); at run time a coming_soon field is
  null + listed in ``meta.unavailable`` — never a fabricated number, and an
  ``available`` field is never silently nulled as if unavailable.
* cut items (``block_phase``, ``currency``-as-dimension, individual ``unit``,
  ``ar_aging``-as-scalar) are absent entirely — not coming_soon.

Validation (``validate_spec``) only rejects MALFORMED specs (unknown id, empty
metrics, bad op/date) with ``APIError(422)``. Unsupported *combinations*
(metric/dimension grain mismatch, unavailable basis combo) never raise — the
engine degrades them to ``null`` per §3.2.
"""
from __future__ import annotations

from datetime import date

from app.responses import APIError

# Grains — which resolver computes a metric and which dimensions it can be sliced
# by. A metric computes for a dimension set only when every requested dimension
# lists the metric's (effective) grain in its ``grains``; otherwise that cell is
# null (graceful, never an error).
GRAIN_COST_LINE = "cost_line"   # row-level over cost_entries (category/vendor/time/…)
GRAIN_PROJECT = "project"       # per-project service aggregate (project/model/status only)
GRAIN_CASH = "cash"             # monthly cashflow (project + month/quarter/year)
GRAIN_UNIT = "unit"             # unit-sales rollup by unit_type (project + unit_type)

STATUS_AVAILABLE = "available"
STATUS_COMING_SOON = "coming_soon"

# Only these leave the process via GET /studio/catalog. The internal ``grain`` /
# ``grains`` / ``dual`` / ``basis`` mapping is NEVER exposed.
PUBLIC_KEYS = ("id", "label", "type", "group", "description", "status")

# Basis keys a metric may honor (§2 "Hesap bazı"). A metric only reacts to the
# toggles in its ``basis`` set; others are ignored (default), never an error.
BASIS_COST = "cost"
BASIS_CURRENCY = "currency"
BASIS_FINANCING = "financing"
BASIS_VAT = "vat"

# Filter operators accepted on spec.filters (validated; anything else → 422).
FILTER_OPS = {"=", "!=", "in", "not_in"}
VIZ_KINDS = {"line", "area", "bar", "kpi", "table"}
HARD_ROW_LIMIT = 1000


# --------------------------------------------------------------------------- #
# §3.1 — Dimensions (ordered; v1 build set per §3.3)
# --------------------------------------------------------------------------- #
def _dim(label, type_, group, description, grains, status=STATUS_AVAILABLE):
    return {
        "label": label, "type": type_, "group": group, "description": description,
        "grains": frozenset(grains), "status": status,
    }


# Time grains used by cost-line and (month/quarter/year) cash metrics.
_TIME_COST = {GRAIN_COST_LINE}
_TIME_COST_CASH = {GRAIN_COST_LINE, GRAIN_CASH}
# Project-attribute dimensions can slice cost-line and project grains. NOT cash:
# cashflow is monthly-per-project and is only sliced by project + time (the cash
# resolver has no revenue_model/project_status axis), so declaring it here would
# let a valid spec reach an unhandled axis and crash instead of degrading to null.
_PROJECT_ATTR = {GRAIN_COST_LINE, GRAIN_PROJECT}

DIMENSIONS: dict[str, dict] = {
    "project": _dim(
        "Proje", "enum", "Proje", "Projeye göre kır.",
        {GRAIN_COST_LINE, GRAIN_PROJECT, GRAIN_CASH, GRAIN_UNIT},
    ),
    "revenue_model": _dim(
        "Proje tipi / gelir modeli", "enum", "Proje",
        "Gelir modeline göre kır (hakediş, kat karşılığı, yap-sat…).", _PROJECT_ATTR,
    ),
    "project_status": _dim(
        "Proje durumu", "enum", "Proje", "Proje durumuna göre kır (aktif, tamamlandı…).",
        _PROJECT_ATTR,
    ),
    "cost_category": _dim(
        "Maliyet kategorisi", "enum", "Maliyet", "Maliyet kategorisine göre kır.",
        {GRAIN_COST_LINE},
    ),
    "cost_subcategory": _dim(
        "Alt kategori", "enum", "Maliyet", "Maliyet alt kategorisine göre kır.",
        {GRAIN_COST_LINE},
    ),
    "entry_type": _dim(
        "Gider tipi", "enum", "Maliyet", "Gerçekleşen / taahhüt / tahmin kırılımı.",
        {GRAIN_COST_LINE},
    ),
    "vendor": _dim(
        "Tedarikçi", "enum", "Taraf", "Tedarikçiye göre kır.", {GRAIN_COST_LINE},
    ),
    "subcontractor": _dim(
        "Taşeron", "enum", "Taraf", "Taşerona göre kır.", {GRAIN_COST_LINE},
    ),
    "unit_type": _dim(
        "Daire tipi", "enum", "Konut",
        "Daire tipine göre kır (satış geliri / kâr — daire tipi grain).", {GRAIN_UNIT},
    ),
    "week": _dim("Hafta", "date", "Zaman", "Haftaya göre kır (ISO hafta).", _TIME_COST),
    "month": _dim("Ay", "date", "Zaman", "Aya göre kır.", _TIME_COST_CASH),
    "quarter": _dim("Çeyrek", "date", "Zaman", "Çeyreğe göre kır.", _TIME_COST_CASH),
    "year": _dim("Yıl", "date", "Zaman", "Yıla göre kır.", _TIME_COST_CASH),
    "payment_status": _dim(
        "Ödeme durumu", "enum", "Para",
        "Ödeme durumuna göre kır (ödendi / kısmi / gecikmiş / ödenmedi).",
        {GRAIN_COST_LINE},
    ),
}


# --------------------------------------------------------------------------- #
# §3.2 — Metrics (ordered; v1 build set per §3.3)
# --------------------------------------------------------------------------- #
def _metric(label, type_, group, description, grain, basis, *, dual=False,
            status=STATUS_AVAILABLE):
    return {
        "label": label, "type": type_, "group": group, "description": description,
        "grain": grain, "dual": dual, "basis": frozenset(basis), "status": status,
    }


METRICS: dict[str, dict] = {
    # --- Maliyet (cost-line grain) ---
    "cost_try": _metric(
        "Maliyet (₺)", "currency", "Maliyet", "Gerçekleşen maliyet (₺), CR-023 baz-duyarlı.",
        GRAIN_COST_LINE, {BASIS_COST, BASIS_VAT},
    ),
    "cost_usd": _metric(
        "Maliyet ($)", "currency", "Maliyet", "Gerçekleşen maliyet ($ anlık kur snapshotu).",
        GRAIN_COST_LINE, {BASIS_COST},
    ),
    "committed": _metric(
        "Taahhüt", "currency", "Maliyet", "Brüt taahhüt (entry_type=committed).",
        GRAIN_COST_LINE, {BASIS_CURRENCY, BASIS_VAT},
    ),
    "open_commitment": _metric(
        "Açık Taahhüt", "currency", "Maliyet",
        "Açık taahhüt = max(taahhüt − bağlı gerçekleşen, 0) (CR-023).",
        GRAIN_COST_LINE, {BASIS_CURRENCY, BASIS_VAT},
    ),
    "exposure": _metric(
        "Maruziyet", "currency", "Maliyet", "Gerçekleşen + açık taahhüt.",
        GRAIN_COST_LINE, {BASIS_CURRENCY, BASIS_VAT},
    ),
    # --- Maliyet / Bütçe (project grain) ---
    "budget": _metric(
        "Bütçe", "currency", "Maliyet", "Revize bütçe.", GRAIN_PROJECT, {BASIS_CURRENCY},
    ),
    "forecast_final": _metric(
        "Tahmini Final Maliyet", "currency", "Maliyet", "forecast_at_completion.",
        GRAIN_PROJECT, {BASIS_CURRENCY},
    ),
    # --- Gelir & Kâr (project grain; unit_sales_revenue/pnl/gross_margin/margin
    # are dual: unit grain when grouped by unit_type) ---
    "revenue": _metric(
        "Gelir", "currency", "Gelir & Kâr",
        "Gelir-modeli duyarlı gelir (sales.project_pnl — asla çift sayılmaz).",
        GRAIN_PROJECT, {BASIS_CURRENCY, BASIS_VAT},
    ),
    "progress_billing": _metric(
        "Hakediş", "currency", "Gelir & Kâr", "İşverene kesilen hakediş faturaları.",
        GRAIN_PROJECT, {BASIS_CURRENCY},
    ),
    "unit_sales_revenue": _metric(
        "Daire satış geliri", "currency", "Gelir & Kâr", "Daire satış geliri (CR-031).",
        GRAIN_PROJECT, {BASIS_CURRENCY}, dual=True,
    ),
    "pnl": _metric(
        "Kâr/Zarar", "currency", "Gelir & Kâr", "Gelir − maliyet (baz-duyarlı).",
        GRAIN_PROJECT, {BASIS_CURRENCY, BASIS_FINANCING}, dual=True,
    ),
    "gross_margin": _metric(
        "Brüt marj", "currency", "Gelir & Kâr", "Gelir − maliyet.",
        GRAIN_PROJECT, {BASIS_CURRENCY}, dual=True,
    ),
    "margin_pct_current": _metric(
        "Güncel kâr marjı", "percent", "Gelir & Kâr", "Brüt marj / gelir.",
        GRAIN_PROJECT, set(), dual=True,
    ),
    "margin_pct_forecast": _metric(
        "Tahmini kâr marjı", "percent", "Gelir & Kâr",
        "Tahmini final gelir/maliyet marjı.", GRAIN_PROJECT, {BASIS_FINANCING},
    ),
    "net_profit_excl_fin": _metric(
        "Net kâr (fin. hariç)", "currency", "Gelir & Kâr", "project_pnl net, finansman hariç.",
        GRAIN_PROJECT, {BASIS_CURRENCY},
    ),
    "net_profit_incl_fin": _metric(
        "Net kâr (fin. dahil)", "currency", "Gelir & Kâr",
        "project_pnl net + finansman maliyeti (CR-015).", GRAIN_PROJECT, {BASIS_CURRENCY},
    ),
    # --- Nakit (cash grain) ---
    "cash_in": _metric(
        "Nakit giriş", "currency", "Nakit", "Aylık nakit giriş.", GRAIN_CASH, {},
    ),
    "cash_out": _metric(
        "Nakit çıkış", "currency", "Nakit", "Aylık nakit çıkış.", GRAIN_CASH, {},
    ),
    "net_cash": _metric(
        "Net nakit", "currency", "Nakit", "Aylık net nakit.", GRAIN_CASH, {},
    ),
    "cum_cash": _metric(
        "Kümülatif nakit", "currency", "Nakit", "Kümülatif nakit pozisyonu.", GRAIN_CASH, {},
    ),
    # --- Alacak (project grain) ---
    "receivables": _metric(
        "Açık alacak", "currency", "Alacak", "Açık işveren faturası bakiyesi.",
        GRAIN_PROJECT, {},
    ),
    # --- m² & Getiri (project grain) ---
    "cost_per_m2": _metric(
        "Maliyet / m²", "currency", "m² & Getiri", "Maliyet ÷ inşaat net m².",
        GRAIN_PROJECT, {BASIS_CURRENCY},
    ),
    "revenue_per_m2": _metric(
        "Gelir / m²", "currency", "m² & Getiri", "Gelir ÷ inşaat net m².",
        GRAIN_PROJECT, {BASIS_CURRENCY},
    ),
    "profit_per_m2": _metric(
        "Kâr / m²", "currency", "m² & Getiri", "Net kâr ÷ inşaat net m².",
        GRAIN_PROJECT, {BASIS_CURRENCY},
    ),
    "irr": _metric(
        "IRR", "percent", "m² & Getiri", "XIRR (sales.investment_return).",
        GRAIN_PROJECT, {},
    ),
    "roi": _metric(
        "ROI", "percent", "m² & Getiri", "ROI = net kâr / maliyet.", GRAIN_PROJECT, {},
    ),
    # --- İlerleme (project grain) ---
    "billing_vs_contract": _metric(
        "Hakediş / sözleşme", "percent", "İlerleme", "Kümülatif hakediş ÷ sözleşme.",
        GRAIN_PROJECT, {},
    ),
    # --- Coming soon (badged "Yakında"; null + meta.unavailable at run) ---
    "dso": _metric(
        "DSO", "number", "Alacak", "Tahsilat süresi (gün). Yakında.",
        GRAIN_PROJECT, {}, status=STATUS_COMING_SOON,
    ),
    "schedule_progress": _metric(
        "Takvim ilerleme %", "percent", "İlerleme", "Ağırlıklı milestone ilerleme. Yakında.",
        GRAIN_PROJECT, {}, status=STATUS_COMING_SOON,
    ),
}


# --------------------------------------------------------------------------- #
# Public projection — id/label/type/group/description/status ONLY
# --------------------------------------------------------------------------- #
def _public(reg: dict[str, dict]) -> list[dict]:
    out = []
    for key, entry in reg.items():
        row = {"id": key}
        for k in PUBLIC_KEYS:
            if k == "id":
                continue
            row[k] = entry[k]
        out.append(row)
    return out


def get_catalog_public() -> dict:
    """The catalog payload for ``GET /studio/catalog`` — public fields only.

    Returns BOTH available and coming_soon entries (the picker greys coming_soon
    with a "Yakında" badge). The internal source/grain mapping is never included.
    """
    return {"dimensions": _public(DIMENSIONS), "metrics": _public(METRICS)}


# --------------------------------------------------------------------------- #
# Validation — reject MALFORMED specs only (never unsupported combinations)
# --------------------------------------------------------------------------- #
def _bad(message: str, field: str | None = None):
    raise APIError(422, "VALIDATION_ERROR", message, field)


def _parse_iso(value, field) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        _bad(f"Geçersiz tarih: {value!r}", field)


def validate_spec(spec: dict) -> None:
    """Validate a spec against the catalog. Raises ``APIError(422)`` on a
    malformed spec; returns None on success. Unknown ids, empty metrics, bad
    filter ops and absurd date ranges are rejected here — unsupported metric/
    dimension *combinations* are NOT (they degrade to null in the engine)."""
    if not isinstance(spec, dict):
        _bad("Spec bir nesne olmalı")

    metrics = spec.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        _bad("En az bir metrik gerekli", "metrics")
    for m in metrics:
        if m not in METRICS:
            _bad(f"Bilinmeyen metrik: {m!r}", "metrics")

    dimensions = spec.get("dimensions", [])
    if not isinstance(dimensions, list):
        _bad("dimensions bir liste olmalı", "dimensions")
    for d in dimensions:
        if d not in DIMENSIONS:
            _bad(f"Bilinmeyen boyut: {d!r}", "dimensions")

    viz = spec.get("viz", "table")
    if viz not in VIZ_KINDS:
        _bad(f"Geçersiz görselleştirme: {viz!r}", "viz")

    filters = spec.get("filters") or []
    if not isinstance(filters, list):
        _bad("filters bir liste olmalı", "filters")
    for f in filters:
        if not isinstance(f, dict):
            _bad("Her filtre bir nesne olmalı", "filters")
        if f.get("field") not in DIMENSIONS:
            _bad(f"Bilinmeyen filtre alanı: {f.get('field')!r}", "filters")
        if f.get("op") not in FILTER_OPS:
            _bad(f"Geçersiz filtre operatörü: {f.get('op')!r}", "filters")
        if "value" not in f:
            _bad("Filtre değeri eksik", "filters")

    _validate_window(spec.get("date_range"), "date_range")
    cmp = spec.get("comparison")
    if cmp is not None and not (isinstance(cmp, dict) and cmp.get("preset") == "previous_period"):
        _validate_window(cmp, "comparison")

    sort = spec.get("sort")
    if sort is not None:
        if not isinstance(sort, dict) or "by" not in sort:
            _bad("sort.by gerekli", "sort")
        by = sort["by"]
        if by not in METRICS and by not in DIMENSIONS:
            _bad(f"Bilinmeyen sıralama alanı: {by!r}", "sort")
        if sort.get("dir", "desc") not in ("asc", "desc"):
            _bad("sort.dir 'asc' veya 'desc' olmalı", "sort")

    limit = spec.get("limit")
    if limit is not None and (not isinstance(limit, int) or limit <= 0):
        _bad("limit pozitif bir tam sayı olmalı", "limit")

    chart = spec.get("chart")
    if chart is not None:
        if not isinstance(chart, dict):
            _bad("chart bir nesne olmalı", "chart")
        x = chart.get("x")
        if x is not None and x not in DIMENSIONS:
            _bad(f"Bilinmeyen chart.x: {x!r}", "chart")
        for side in ("y_left", "y_right"):
            ys = chart.get(side)
            if ys is None:
                continue
            if not isinstance(ys, list):
                _bad(f"chart.{side} bir liste olmalı", "chart")
            for y in ys:
                if y not in METRICS:
                    _bad(f"Bilinmeyen chart.{side} metriği: {y!r}", "chart")


def _validate_window(window, field) -> None:
    """A date_range / comparison is either {preset} (resolvable) or {from,to}."""
    if window is None:
        return
    if not isinstance(window, dict):
        _bad(f"{field} bir nesne olmalı", field)
    if "preset" in window:
        from app.services.studio.engine import is_known_preset

        if not is_known_preset(window["preset"]):
            _bad(f"Bilinmeyen dönem: {window['preset']!r}", field)
        return
    if "from" in window or "to" in window:
        d_from = _parse_iso(window.get("from"), field)
        d_to = _parse_iso(window.get("to"), field)
        if d_from > d_to:
            _bad(f"{field}: başlangıç bitişten sonra olamaz", field)
        if (d_to - d_from).days > 366 * 15:
            _bad(f"{field}: tarih aralığı çok geniş", field)
        return
    _bad(f"{field}: preset veya from/to gerekli", field)
