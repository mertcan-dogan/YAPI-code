"""CR-046 — decision-grade Excel report engine.

Turns already-computed ``run_spec`` results into a board-ready workbook:
  * Sheet 1 **"Özet"** — a Heneka header band, KPI cards (most-important top-left),
    and native Excel charts (``openpyxl.chart`` Bar/Line/Pie) that reference the
    data-sheet ranges, so they stay live if the user edits.
  * **Data sheets** (consolidated per table/section, NOT one-per-KPI) — navy headers,
    banded rows, autofilter, frozen header, ₺/% number formats, a "Toplam" totals row
    (the authoritative ``run_spec`` total, written as a value), and variance columns
    with RAG conditional formatting.

STRICTLY READ-ONLY: it consumes a result dict (no DB session, no queries, no writes).
**No fabrication** — every figure comes from ``run_spec``; the engine only adds
layout/charts/formatting, never numbers. The single ``_safe_cell`` formula-injection
guard (from ``export.py``) is applied to every user-authored string.

Both xlsx entry points route here: ``export._dashboard_xlsx`` (skills + dashboard
deck) and the xlsx branch of ``export.studio_export`` (single report). The PDF
(CR-037) and CSV (422) paths are untouched.
"""
import io
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.chart import AreaChart, BarChart, LineChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.responses import APIError
from app.services.report_theme import (
    BG, CARD, GOLD, GREEN, HAIR, INK, MUT, NAVY, PETROL, RED, TINT,
)
from app.services.studio.catalog import GRAIN_CASH, GRAIN_COST_LINE, METRICS
from app.services.studio.export import _is_renderable, _safe_cell, _sheet_name

# --------------------------------------------------------------------------- #
# Palette → openpyxl ARGB + reusable styles
# --------------------------------------------------------------------------- #
def _argb(hex_str: str) -> str:
    """'#183047' → 'FF183047' (openpyxl wants ARGB, alpha first)."""
    return "FF" + hex_str.lstrip("#").upper()


_FONT = "Calibri"
_navy_fill = PatternFill("solid", fgColor=_argb(NAVY))
_gold_fill = PatternFill("solid", fgColor=_argb(GOLD))
_card_fill = PatternFill("solid", fgColor=_argb(BG))
_band_fill = PatternFill("solid", fgColor="FFF3F4F0")  # subtle zebra (BG, lighter)
_white_bold = Font(name=_FONT, bold=True, color="FFFFFFFF")
_white = Font(name=_FONT, color="FFFFFFFF")
_white_title = Font(name=_FONT, bold=True, size=16, color="FFFFFFFF")
_muted = Font(name=_FONT, size=9, color=_argb(MUT))
_value_font = Font(name=_FONT, bold=True, size=18, color=_argb(NAVY))
_ink = Font(name=_FONT, color=_argb(INK))
_bold = Font(name=_FONT, bold=True, color=_argb(INK))
_hair = Side(style="thin", color=_argb(HAIR))
_thin_border = Border(left=_hair, right=_hair, top=_hair, bottom=_hair)
_green_tint = PatternFill("solid", fgColor=_argb(TINT["g"]))
_red_tint = PatternFill("solid", fgColor=_argb(TINT["r"]))
_green_font = Font(name=_FONT, bold=True, color=_argb(GREEN))
_red_font = Font(name=_FONT, bold=True, color=_argb(RED))
_grey_font = Font(name=_FONT, color=_argb(MUT))

# Number formats — ₺ with negatives in parens (red) and zeros as an en-dash.
_FMT_TRY = '#,##0" ₺";[Red](#,##0)" ₺";"–"'
_FMT_PCT = "0.0%"
_FMT_NUM = '#,##0;[Red](#,##0);"–"'
# CR-047 — a model-inapplicable metric is None; show the en-dash (a numeric format's
# zero-section only fires for an actual 0, so a None/blank cell would otherwise be empty).
_DASH = "–"

_TR_MONTHS = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
              "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _num_fmt(col_type: str) -> str:
    if col_type == "currency":
        return _FMT_TRY
    if col_type == "percent":
        return _FMT_PCT
    return _FMT_NUM


# --------------------------------------------------------------------------- #
# Metric metadata (read-only, from the catalog) — snapshot + favourable direction
# --------------------------------------------------------------------------- #
def _is_snapshot(metric_id: str) -> bool:
    """A non-windowed / whole-project snapshot metric (e.g. hakediş, forecast):
    its grain is not a time-series grain, so grouping it by month yields blank rows.
    Mirrors ``export._has_unwindowed_metric``."""
    m = METRICS.get(metric_id)
    return bool(m) and m["grain"] not in (GRAIN_COST_LINE, GRAIN_CASH)


# Non-cost metrics where an INCREASE is unfavourable (more outflow / more unpaid /
# slower collection). Cost-group metrics are already caught by the group check below.
_UNFAVOURABLE_UP = {"cash_out", "receivables", "dso"}


def _favourable_up(metric_id: str) -> bool:
    """RAG direction: for cost metrics, cash outflow, open receivables and DSO an
    increase is UNFAVOURABLE (red); for revenue/profit/margin/inflow an increase is
    favourable (green)."""
    if metric_id in _UNFAVOURABLE_UP:
        return False
    m = METRICS.get(metric_id)
    return not (m and m.get("group") == "Maliyet")


def _is_time_grouped(columns: list) -> bool:
    return any(c.get("kind") == "dimension" and c.get("type") == "date" for c in columns)


# --------------------------------------------------------------------------- #
# Period label (Turkish) from the result meta — no query
# --------------------------------------------------------------------------- #
def _period_label(result: dict) -> str:
    dr = ((result or {}).get("meta") or {}).get("date_range") or {}
    f, t = dr.get("from"), dr.get("to")
    if not f and not t:
        # CR-049 — an all-time window: label from the REAL span the result covers
        # (its date-bucket rows), e.g. "2018 – 2020"; "Tüm zamanlar" when the report
        # carries no time dimension. Never a hardcoded recent range.
        return _all_time_label(result)
    try:
        fd = datetime.fromisoformat(f) if f else None
        td = datetime.fromisoformat(t) if t else None
    except (TypeError, ValueError):
        return f"{f or '—'} – {t or '—'}"
    if fd and td and fd.year == td.year and fd.month == td.month:
        return f"{_TR_MONTHS[fd.month]} {fd.year}"
    fs = f"{_TR_MONTHS[fd.month]} {fd.year}" if fd else "—"
    ts = f"{_TR_MONTHS[td.month]} {td.year}" if td else "—"
    return f"{fs} – {ts}"


def _all_time_label(result: dict) -> str:
    """CR-049 — derive the span an all-time result actually covers from any date-typed
    dimension buckets in its rows (month '2018-01' / quarter '2018-Q1' / year '2018' —
    the leading 4 digits are the year). Returns '2018 – 2020' (or a single '2018'), or
    'Tüm zamanlar' when the report has no time dimension to read a span from."""
    date_ids = [c.get("id") for c in (result.get("columns") or [])
                if c.get("kind") == "dimension" and c.get("type") == "date"]
    years: set[int] = set()
    for row in (result.get("rows") or []) if date_ids else []:
        dims = row.get("dims") or {}
        for did in date_ids:
            v = dims.get(did)
            if isinstance(v, str) and len(v) >= 4 and v[:4].isdigit():
                years.add(int(v[:4]))
    if not years:
        return "Tüm zamanlar"
    lo, hi = min(years), max(years)
    return str(lo) if lo == hi else f"{lo} – {hi}"


# --------------------------------------------------------------------------- #
# Header band
# --------------------------------------------------------------------------- #
def header_band(ws, title: str, company: str | None, period: str, start_row: int = 1) -> int:
    """Navy band: company / title / period / 'Yapı AI ile üretildi · {tarih}' + a gold
    rule. Returns the next free row. Every string is _safe_cell-guarded."""
    span = 8
    last_col = get_column_letter(span)
    rows = [
        (_safe_cell(company or "YAPI"), _white_bold, 13),
        (_safe_cell(title or "Rapor"), _white_title, 18),
        (_safe_cell(period or ""), _white, 11),
        (_safe_cell(f"Yapı AI ile üretildi · {datetime.now(timezone.utc):%d.%m.%Y}"), _white, 9),
    ]
    r = start_row
    for text, font, height in rows:
        ws.merge_cells(f"A{r}:{last_col}{r}")
        cell = ws.cell(row=r, column=1, value=text)
        cell.font = font
        cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        for ci in range(1, span + 1):
            ws.cell(row=r, column=ci).fill = _navy_fill
        ws.row_dimensions[r].height = height
        r += 1
    # gold rule
    ws.merge_cells(f"A{r}:{last_col}{r}")
    for ci in range(1, span + 1):
        ws.cell(row=r, column=ci).fill = _gold_fill
    ws.row_dimensions[r].height = 4
    return r + 2


# --------------------------------------------------------------------------- #
# KPI cards
# --------------------------------------------------------------------------- #
def kpi_cards(ws, cards: list, start_row: int) -> int:
    """A 2–4-across grid of cards: muted label / large ₺ value / RAG delta. ``cards``
    are dicts {label, value, value_type, delta, favourable_up}. Returns next free row."""
    if not cards:
        return start_row
    per_row = 4
    col_pairs = [(1, 2), (3, 4), (5, 6), (7, 8)]  # each card spans 2 cols
    r = start_row
    for i in range(0, len(cards), per_row):
        band = cards[i:i + per_row]
        for j, card in enumerate(band):
            c0, c1 = col_pairs[j]
            cl0, cl1 = get_column_letter(c0), get_column_letter(c1)
            # label
            ws.merge_cells(f"{cl0}{r}:{cl1}{r}")
            lc = ws.cell(row=r, column=c0, value=_safe_cell(card["label"]))
            lc.font = _muted
            lc.alignment = Alignment(horizontal="left", indent=1)
            # value — a model-inapplicable metric is None → render the CR's "–", not blank.
            ws.merge_cells(f"{cl0}{r + 1}:{cl1}{r + 1}")
            vc = ws.cell(row=r + 1, column=c0)
            val = card.get("value")
            if val is None:
                vc.value = _DASH
            else:
                vc.value = val
                vc.number_format = _num_fmt(card.get("value_type") or "currency")
            vc.font = _value_font
            vc.alignment = Alignment(horizontal="left", indent=1)
            # delta — a styled string (arrow + %), RAG-coloured by favourable direction.
            ws.merge_cells(f"{cl0}{r + 2}:{cl1}{r + 2}")
            dc = ws.cell(row=r + 2, column=c0)
            delta = card.get("delta")
            if delta is None:
                dc.value = "—"
                dc.font = _grey_font
            else:
                d = float(delta)
                arrow = "▲" if d > 0 else ("▼" if d < 0 else "■")
                if card.get("delta_unit") == "abs":
                    # An absolute ₺/number difference, not a fraction.
                    unit_suffix = " ₺" if card.get("value_type") == "currency" else ""
                    dc.value = f"{arrow} {abs(d):,.0f}{unit_suffix}"
                else:
                    dc.value = f"{arrow} %{abs(d) * 100:.1f}"
                fav = card.get("favourable_up", True)
                dc.font = _grey_font if d == 0 else (_green_font if (d > 0) == fav else _red_font)
            dc.alignment = Alignment(horizontal="left", indent=1)
            # card border on the 3 rows
            for rr in (r, r + 1, r + 2):
                for cc in (c0, c1):
                    ws.cell(row=rr, column=cc).border = _thin_border
                    if rr != r:
                        ws.cell(row=rr, column=cc).fill = _card_fill
        r += 4  # 3 card rows + 1 gap
    return r


# --------------------------------------------------------------------------- #
# Data sheet (consolidated table) — returns chart-range info
# --------------------------------------------------------------------------- #
def data_sheet(wb, result: dict, sheet_title: str, used_names: set) -> dict | None:
    """Write a styled data sheet from a result. Snapshot metrics in a time-grouped
    table are dropped here (rerouted to KPI cards by the caller). Returns a dict with
    the chart-range info ({sheet, cat_col, metric_cols, header_row, last_data_row}) or
    None when there is nothing tabular to render."""
    all_columns = result.get("columns") or []
    rows = result.get("rows") or []
    time_grouped = _is_time_grouped(all_columns)
    # Drop snapshot metric columns from a time-grouped table (the Hakediş bug).
    columns = [
        c for c in all_columns
        if not (c.get("kind") == "metric" and time_grouped and _is_snapshot(c["id"]))
    ]
    metric_cols = [c for c in columns if c.get("kind") == "metric"]
    dim_cols = [c for c in columns if c.get("kind") == "dimension"]
    if not columns or not rows or not metric_cols:
        return None

    has_delta = bool(((result.get("meta") or {}).get("comparison")))
    delta_unit = ((result.get("meta") or {}).get("comparison_unit")) or "pct"

    def _delta_fmt(col: dict) -> str:
        # pct deltas are fractions → 0.0%; abs deltas are ₺/number differences.
        return _FMT_PCT if delta_unit == "pct" else _num_fmt(col.get("type"))

    name = _sheet_name(sheet_title, used_names)
    used_names.add(name)
    ws = wb.create_sheet(title=name)

    # Column plan: [dims...] [metrics...] [Δ metrics... (if comparison)]
    plan: list = []  # (col_index, col_dict, role)  role: dim|metric|delta
    ci = 1
    for c in dim_cols:
        plan.append((ci, c, "dim")); ci += 1
    metric_first_col = ci
    for c in metric_cols:
        plan.append((ci, c, "metric")); ci += 1
    metric_last_col = ci - 1
    delta_cols: list = []
    if has_delta:
        for c in metric_cols:
            plan.append((ci, c, "delta")); delta_cols.append((ci, c)); ci += 1
    ncols = ci - 1

    # Header row
    for col_idx, c, role in plan:
        label = c["label"] if role != "delta" else f"Δ {c['label']}"
        cell = ws.cell(row=1, column=col_idx, value=_safe_cell(label))
        cell.font = _white_bold
        cell.fill = _navy_fill
        cell.alignment = Alignment(horizontal=("left" if role == "dim" else "right"), vertical="center")

    # Data rows
    for ri, row in enumerate(rows, start=2):
        dims = row.get("dims") or {}
        metrics = row.get("metrics") or {}
        deltas = row.get("deltas") or {}
        banded = (ri % 2 == 0)
        for col_idx, c, role in plan:
            if role == "dim":
                v = dims.get(c["id"])
                cell = ws.cell(row=ri, column=col_idx, value=_safe_cell(v))
            elif role == "metric":
                mv = metrics.get(c["id"])
                if mv is None:  # CR-047 — model-inapplicable metric → "–", not blank
                    cell = ws.cell(row=ri, column=col_idx, value=_DASH)
                else:
                    cell = ws.cell(row=ri, column=col_idx, value=mv)
                    cell.number_format = _num_fmt(c["type"])
            else:  # delta (fraction for pct; absolute ₺/number for abs)
                cell = ws.cell(row=ri, column=col_idx, value=deltas.get(c["id"]))
                cell.number_format = _delta_fmt(c)
            cell.font = _ink
            if banded:
                cell.fill = _band_fill
    last_data_row = 1 + len(rows)

    # "Toplam" totals row — authoritative run_spec values (NOT a re-sum formula),
    # so the sheet total can never diverge from the trusted engine total.
    totals = (result.get("totals") or {}).get("metrics") or {}
    total_deltas = (result.get("totals") or {}).get("deltas") or {}
    trow = last_data_row + 1
    label_placed = False
    for col_idx, c, role in plan:
        cell = ws.cell(row=trow, column=col_idx)
        if role == "dim":
            cell.value = _safe_cell("Toplam") if not label_placed else None
            label_placed = True
        elif role == "metric":
            tv = totals.get(c["id"])
            if tv is None:  # CR-047 — "–" for a model-inapplicable total
                cell.value = _DASH
            else:
                cell.value = tv
                cell.number_format = _num_fmt(c["type"])
        else:
            cell.value = (total_deltas or {}).get(c["id"]) if total_deltas else None
            cell.number_format = _delta_fmt(c)
        cell.font = _bold
        cell.fill = _gold_fill if role != "dim" else _gold_fill

    # RAG conditional formatting on each Δ column (favourable green / unfavourable red)
    for col_idx, c in delta_cols:
        col = get_column_letter(col_idx)
        rng = f"{col}2:{col}{last_data_row}"
        up_fav = _favourable_up(c["id"])
        good = PatternFill("solid", fgColor=_argb(TINT["g"]))
        bad = PatternFill("solid", fgColor=_argb(TINT["r"]))
        ws.conditional_formatting.add(rng, CellIsRule(
            operator="greaterThan", formula=["0"], fill=(good if up_fav else bad)))
        ws.conditional_formatting.add(rng, CellIsRule(
            operator="lessThan", formula=["0"], fill=(bad if up_fav else good)))

    # Autofilter, freeze, widths
    ws.auto_filter.ref = f"A1:{get_column_letter(ncols)}{last_data_row}"
    ws.freeze_panes = "A2"
    for col_idx, c, role in plan:
        ws.column_dimensions[get_column_letter(col_idx)].width = 30 if role == "dim" else 16

    # Chart range info: categories = first dim column, values = the metric block.
    cat_col = plan[0][0] if dim_cols else None
    return {
        "sheet": ws,
        "cat_col": cat_col,
        "metric_first_col": metric_first_col,
        "metric_last_col": metric_last_col,
        "header_row": 1,
        "last_data_row": last_data_row,
        "metric_cols": metric_cols,
        "dim_cols": dim_cols,
        "time_grouped": time_grouped,
    }


# --------------------------------------------------------------------------- #
# Native charts referencing the data-sheet ranges
# --------------------------------------------------------------------------- #
# CR-046 Heneka categorical palette (mirrors report_charts._PALETTE / _DONUT_PALETTE)
# — series/slices cycle through these so native charts match the PDF deck.
_SERIES_COLORS = [NAVY, PETROL, GOLD, GREEN, "#A9B2AC"]
_AXIS_FMT = '#,##0" ₺"'   # ₺ value-axis ticks (CR-052 §3)
_CAT_CAP = 12             # cap a ranking/composition chart's categories for readability


def _color6(hex_str: str) -> str:
    """'#183047' / '183047' → '183047' (openpyxl solidFill wants 6-hex, no alpha)."""
    return hex_str.lstrip("#").upper()


def _apply_series_colors(chart, *, line: bool) -> None:
    """Recolour every data series with the Heneka palette. Defensive: a styling
    failure must NEVER break the workbook (the file-opens-clean invariant)."""
    try:
        for i, s in enumerate(chart.series):
            color = _color6(_SERIES_COLORS[i % len(_SERIES_COLORS)])
            if line:
                gp = GraphicalProperties()
                gp.line = LineProperties(solidFill=color, w=28575)  # ~2.25pt
                s.graphicalProperties = gp
            else:
                s.graphicalProperties = GraphicalProperties(solidFill=color)
    except Exception:
        pass


def _apply_pie_colors(chart, n_points: int) -> None:
    """Colour each pie slice from the Heneka palette (per-point, not per-series)."""
    try:
        if not chart.series:
            return
        ser = chart.series[0]
        for i in range(max(0, n_points)):
            color = _color6(_SERIES_COLORS[i % len(_SERIES_COLORS)])
            # openpyxl's DataPoint constructor takes ``spPr`` (graphicalProperties is a
            # read-only alias); passing graphicalProperties= raises TypeError → no colors.
            ser.data_points.append(
                DataPoint(idx=i, spPr=GraphicalProperties(solidFill=color)))
    except Exception:
        pass


def _style_chart(chart, title: str, *, legend: bool = True):
    chart.title = _safe_cell(title or "Grafik")
    chart.height = 8
    chart.width = 16
    if legend:
        try:
            chart.legend.position = "b"
        except AttributeError:
            pass
    else:
        chart.legend = None  # a single-series chart needs no legend


def _filter_key(spec: dict) -> tuple:
    """A stable, hashable key for a widget's filters, so the chart de-dup treats two
    widgets with the same metric+dim but DIFFERENT filters as distinct (not twins)."""
    out = []
    for f in (spec or {}).get("filters") or []:
        if isinstance(f, dict):
            out.append((str(f.get("field")), str(f.get("op")), str(f.get("value"))))
    return tuple(sorted(out))


def pick_chart(columns: list, rows: list, viz: str | None) -> str | None:
    """CR-052 — pick the chart that the data SHAPE earns, or ``None`` (a chart that
    merely restates the table beside it is clutter). Returns one of
    ``line|area|bar|clustered_bar|pie|None``:

      * **date dim** + 1 metric → ``line`` (``area`` when explicitly cumulative),
        + ≥2 metrics → ``clustered_bar`` (e.g. gelir vs gider);
      * **one category dim** + 1 metric, >3 rows → ``bar`` (horizontal ranking),
        ≤6 rows of a summable ₺ metric → ``pie`` (part-to-whole composition),
        + ≥2 metrics → ``clustered_bar`` (bütçe/gerçekleşen/taahhüt side-by-side);
      * **snapshot / single value / ≤3 rows / lookup / 0 or >1 dims** → ``None``.

    An explicit ``viz`` is honoured (``area``/``bar`` on a time series) but the shape
    overrides it to ``None`` when no chart helps, and upgrades a generic ``bar`` to
    ``clustered_bar``/``pie`` when the shape fits. ``columns`` are the RENDERED columns
    (snapshot metrics already dropped by ``data_sheet``)."""
    dim_cols = [c for c in columns if c.get("kind") == "dimension"]
    metric_cols = [c for c in columns if c.get("kind") == "metric"]
    n_rows = len(rows or [])
    n_metrics = len(metric_cols)

    # Need exactly one dimension to plot against and at least one metric. Zero dims is a
    # snapshot KPI; multiple dims is a cross-tab a single-axis chart only muddles.
    if len(dim_cols) != 1 or n_metrics == 0:
        return None
    # Too few points to be worth a chart — a KPI card / the table says it better.
    if n_rows < 2:
        return None

    if dim_cols[0].get("type") == "date":
        # Trend over time.
        if n_metrics >= 2:
            return "clustered_bar"
        if viz == "area":
            return "area"
        if viz == "bar":
            return "clustered_bar"   # honour an explicit column-over-time intent
        return "line"

    # One category dimension (kategori / vendor / tip / proje).
    if n_metrics >= 2:
        return "clustered_bar"       # side-by-side metric comparison
    if n_rows <= 3:
        return None                  # ≤3 categories — a KPI/table reads better
    metric = metric_cols[0]
    if metric.get("type") == "currency" and n_rows <= 6:
        return "pie"                 # part-to-whole composition, few slices
    return "bar"                     # ranking / comparison (horizontal bar)


def add_chart(ozet, ref: dict, kind: str, title: str, anchor: str):
    """Build a native chart from a data-sheet range info and anchor it on the Özet.
    ``kind`` is a ``pick_chart`` result. Categories on a non-time ranking/composition
    chart are capped (``_CAT_CAP``) for readability; a time series keeps every point so
    the line reads left→right over the whole span (CR-050 chronological order)."""
    sheet = ref["sheet"]
    cat_col = ref["cat_col"]
    hr = ref["header_row"]
    last = ref["last_data_row"]
    mfirst, mlast = ref["metric_first_col"], ref["metric_last_col"]
    if cat_col is None or last <= hr:
        return
    is_time = bool(ref.get("time_grouped"))
    data_last = last if is_time else min(last, hr + _CAT_CAP)
    cats = Reference(sheet, min_col=cat_col, max_col=cat_col, min_row=hr + 1, max_row=data_last)
    multi = mlast > mfirst

    if kind == "pie":
        chart = PieChart()
        data = Reference(sheet, min_col=mfirst, max_col=mfirst, min_row=hr, max_row=data_last)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.dataLabels = DataLabelList(); chart.dataLabels.showPercent = True
        _apply_pie_colors(chart, data_last - hr)
        _style_chart(chart, title, legend=True)
    elif kind in ("line", "area"):
        chart = LineChart() if kind == "line" else AreaChart()
        chart.y_axis.numFmt = _AXIS_FMT
        data = Reference(sheet, min_col=mfirst, max_col=mlast, min_row=hr, max_row=data_last)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        _apply_series_colors(chart, line=(kind == "line"))
        _style_chart(chart, title, legend=multi)
    elif kind == "bar":
        chart = BarChart(); chart.type = "bar"      # horizontal ranking
        chart.x_axis.numFmt = _AXIS_FMT             # value axis is x for a horizontal bar
        data = Reference(sheet, min_col=mfirst, max_col=mfirst, min_row=hr, max_row=data_last)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        _apply_series_colors(chart, line=False)
        _style_chart(chart, title, legend=False)
    else:  # clustered_bar — multi-series columns over the dim
        chart = BarChart(); chart.type = "col"; chart.grouping = "clustered"
        chart.y_axis.numFmt = _AXIS_FMT
        data = Reference(sheet, min_col=mfirst, max_col=mlast, min_row=hr, max_row=data_last)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        _apply_series_colors(chart, line=False)
        _style_chart(chart, title, legend=multi)
    ozet.add_chart(chart, anchor)


# --------------------------------------------------------------------------- #
# Card builders from a result
# --------------------------------------------------------------------------- #
def _cards_from_result(result: dict, *, only_snapshot: bool = False, suffix: str = "") -> list:
    """Build KPI cards from a result's totals. ``only_snapshot`` keeps just snapshot
    metrics (for the time-grouped reroute); otherwise all metric columns."""
    totals = (result.get("totals") or {}).get("metrics") or {}
    deltas = (result.get("totals") or {}).get("deltas") or {}
    unit = ((result.get("meta") or {}).get("comparison_unit")) or "pct"
    cards: list = []
    for c in result.get("columns") or []:
        if c.get("kind") != "metric":
            continue
        mid = c["id"]
        if only_snapshot and not _is_snapshot(mid):
            continue
        cards.append({
            "label": (c.get("label") or mid) + suffix,
            "value": totals.get(mid),
            "value_type": c.get("type"),
            "delta": (deltas or {}).get(mid) if deltas else None,
            "delta_unit": unit,
            "favourable_up": _favourable_up(mid),
        })
    return cards


# --------------------------------------------------------------------------- #
# The orchestrator
# --------------------------------------------------------------------------- #
def build_workbook(widgets: list, results: dict, title: str, *,
                   company: str | None = None, period: str | None = None,
                   single_report: bool = False) -> bytes:
    """Render a decision-grade workbook → bytes. ``widgets`` is the ordered widget
    list (section-grouped by the caller); ``results`` maps widget id → run_spec result
    or {"unavailable": True}. Raises ``APIError(422, NO_DATA)`` when nothing is
    renderable (no empty workbook)."""
    wb = Workbook()
    wb.remove(wb.active)  # drop the default sheet; Özet is inserted at the front later

    used_names: set = set()
    cards: list = []
    chart_candidates: list = []  # CR-052 — {sig, ref, kind, title, explicit}, deduped below
    rendered = False

    # Period from the result windows (no query). CR-049 — prefer a CONCRETE span (a
    # label carrying a year, e.g. "2018 – 2020" / "Ocak 2026 – …") over a bare "Tüm
    # zamanlar", so a multi-widget all-time report whose first widget is a snapshot
    # KPI still headlines the real span a later time-series widget covers.
    if period is None:
        fallback = None
        for w in widgets:
            res = results.get(w.get("id"))
            if isinstance(res, dict) and res.get("meta"):
                label = _period_label(res)
                if fallback is None:
                    fallback = label
                if any(ch.isdigit() for ch in label):
                    period = label
                    break
        period = period or fallback

    for w in widgets:
        wtype = w.get("type")
        if wtype == "text":
            continue
        res = results.get(w.get("id"))

        if wtype == "kpi":
            if _is_renderable(res):
                cards.extend(_cards_from_result(res))
                rendered = True
            continue

        if not _is_renderable(res):
            continue

        columns = res.get("columns") or []
        if single_report:
            # Özet-lite: headline KPI cards from the report's totals (all metrics).
            cards = _cards_from_result(res) + cards
            rendered = True
        elif _is_time_grouped(columns):
            # Snapshot reroute: a snapshot metric in a time-grouped table → KPI card.
            snap_cards = _cards_from_result(res, only_snapshot=True, suffix=" (tüm proje)")
            if snap_cards:
                # A card-only Özet built from authoritative run_spec totals is a valid
                # decision dashboard, so this counts as rendered even if the table that
                # follows drops to nothing (all-snapshot table → no data sheet).
                cards.extend(snap_cards)
                rendered = True

        ref = data_sheet(wb, res, w.get("title") or "Veri", used_names)
        if ref is None:
            # All metrics were snapshot → already rerouted to cards above; no tabular
            # sheet to write for this widget.
            continue
        rendered = True

        # CR-052 — let EVERY rendered table earn a chart by its data shape (not one
        # per table). pick_chart returns None for shapes a chart can't improve, so the
        # Özet stays a curated dashboard. An explicit chart widget's viz is honoured.
        spec = w.get("spec") or {}
        viz = spec.get("viz")
        sheet_columns = (ref["dim_cols"] or []) + (ref["metric_cols"] or [])
        kind = pick_chart(sheet_columns, res.get("rows") or [], viz)
        if kind:
            # Signature includes FILTERS so two same-metric+dim widgets that differ only
            # by filter (e.g. cost-by-month for project A vs B) are NOT collapsed — only
            # a true twin (a table restating a chart's exact data) de-dups.
            sig = (
                tuple(sorted(c["id"] for c in ref["metric_cols"])),
                tuple(c["id"] for c in ref["dim_cols"]),
                _filter_key(spec),
            )
            chart_candidates.append({
                "sig": sig, "ref": ref, "kind": kind,
                "title": w.get("title") or title, "explicit": wtype == "chart",
            })

    if not rendered:
        raise APIError(422, "NO_DATA", "Dışa aktarılacak veri yok")

    # CR-052 de-dup: one chart per (metrics, dims) signature — don't chart a table that
    # a twin chart widget already visualizes. An explicit chart widget wins the twin.
    chosen: dict = {}
    for cand in chart_candidates:
        prev = chosen.get(cand["sig"])
        if prev is None or (cand["explicit"] and not prev["explicit"]):
            chosen[cand["sig"]] = cand
    chart_specs = [(c["ref"], c["kind"], c["title"]) for c in chosen.values()]

    # Build the Özet sheet at the front, now that data sheets exist for chart refs.
    ozet = wb.create_sheet("Özet", 0)
    ozet.sheet_view.showGridLines = False
    next_row = header_band(ozet, title, company, period or "Tüm zamanlar")
    next_row = kpi_cards(ozet, cards, next_row + 1)
    # Anchor charts below the KPIs, stacked.
    anchor_row = next_row + 1
    for ref, kind, ctitle in chart_specs:
        add_chart(ozet, ref, kind, ctitle, f"A{anchor_row}")
        anchor_row += 16  # ~chart height in rows
    for col in range(1, 9):
        ozet.column_dimensions[get_column_letter(col)].width = 18
    ozet.freeze_panes = "A6"
    ozet.print_area = f"A1:H{max(anchor_row, next_row)}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Single-report convenience wrapper (xlsx branch of studio_export)
# --------------------------------------------------------------------------- #
def build_single_report(result: dict, title: str, viz: str | None, *,
                        company: str | None = None) -> bytes:
    """The single-report xlsx: one synthetic widget through the same engine, giving an
    Özet-lite (title band + headline KPIs + the report's own chart) + the data sheet."""
    wtype = "kpi" if viz == "kpi" else ("chart" if viz in ("line", "area", "bar") else "table")
    widget = {"id": "r", "type": wtype, "title": title, "spec": {"viz": viz}}
    if wtype == "kpi":
        # A kpi-viz report: render its totals as cards AND keep a data sheet via the
        # table path, so single_report still surfaces the table. Treat as report.
        widget["type"] = "report"
    return build_workbook([widget], {"r": result}, title, company=company,
                          period=_period_label(result), single_report=True)
