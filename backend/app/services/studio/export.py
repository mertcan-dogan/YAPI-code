"""CR-033 — Report Studio export (pdf / xlsx / csv).

Turns a ``run_spec`` result (§2 shape) into a downloadable file. STRICTLY
READ-ONLY: it consumes an already-computed result dict and builds an in-memory
file — it issues no queries and never writes a row. The flat table is:

    header = [column.label for every column]
    each data row = dim label (dimension cols) / metric value (metric cols)
    a final "Toplam" row from result["totals"]["metrics"]

xlsx mirrors the openpyxl Workbook→bytes pattern in app/api/audit.py; pdf reuses
the Turkish-capable ReportLab helpers in app/services/reports.py
(``register_turkish_fonts`` / ``_styles`` / ``_data_table`` / ``_render_story``) —
no new PDF/Excel dependency is introduced. Chart-as-image is deferred.
"""
import csv
import io
import re
from datetime import datetime, timezone

from fastapi.responses import Response

from app.responses import APIError

CSV_BOM = "﻿"  # Excel needs the UTF-8 BOM to detect Turkish text correctly.

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CSV_MEDIA = "text/csv; charset=utf-8"
_PDF_MEDIA = "application/pdf"

# ASCII transliteration for a safe Content-Disposition filename.
_TR_MAP = str.maketrans({
    "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
    "ö": "o", "Ö": "o", "ü": "u", "Ü": "u", "ç": "c", "Ç": "c",
})


def _slug(title: str) -> str:
    base = (title or "rapor").translate(_TR_MAP).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or "rapor"


# --------------------------------------------------------------------------- #
# Flatten the result into header / data rows / totals row
# --------------------------------------------------------------------------- #
def _flat_table(result: dict) -> tuple[list, list[list], list]:
    columns = result.get("columns") or []
    header = [c.get("label") or c.get("id") for c in columns]

    data_rows: list[list] = []
    for row in result.get("rows") or []:
        dims = row.get("dims") or {}
        metrics = row.get("metrics") or {}
        data_rows.append([
            dims.get(c["id"]) if c.get("kind") == "dimension" else metrics.get(c["id"])
            for c in columns
        ])

    totals = (result.get("totals") or {}).get("metrics") or {}
    totals_row: list = []
    label_placed = False
    for c in columns:
        if c.get("kind") == "dimension":
            totals_row.append("Toplam" if not label_placed else "")
            label_placed = True
        else:
            totals_row.append(totals.get(c["id"]))
    # KPI-style export (no dimension column): label the first cell so the totals
    # row is still distinguishable.
    if columns and not label_placed:
        totals_row[0] = totals_row[0]  # leave metric value; header already names it
    return header, data_rows, totals_row


# --------------------------------------------------------------------------- #
# Cell coercion per format
# --------------------------------------------------------------------------- #
# Formula / CSV-injection guard shared by EVERY spreadsheet + csv writer (the
# per-report _xlsx/_csv and the dashboard deck _dashboard_xlsx).
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(v):
    """Neutralize spreadsheet formula / CSV injection. A *text* cell beginning with a
    formula trigger (``= + - @`` or a leading TAB/CR) is prefixed with a single
    apostrophe so Excel/Sheets/LibreOffice render it as literal text rather than
    evaluate it (``=WEBSERVICE(...)`` / ``=HYPERLINK(...)`` / legacy DDE). Exports only
    ever hold the caller's own company data, but dimension labels are user-authored
    (project / vendor / supplier names), so a lower-privilege user could otherwise
    plant a payload that runs when a colleague opens the file.

    Only applied to genuine strings — callers must pass numbers as native int/float
    (never pre-stringified) so a legitimate negative value like ``-5`` is not mistaken
    for a formula. Numbers and other non-strings pass through unchanged."""
    if isinstance(v, str) and v[:1] in _FORMULA_TRIGGERS:
        return "'" + v
    return v


def _csv_cell(v) -> str:
    # Guard only original text (dimension labels); numbers are stringified WITHOUT the
    # guard so a negative metric (-5.0) stays a number, not "'-5.0".
    if v is None:
        return ""
    if isinstance(v, str):
        return _safe_cell(v)
    return str(v)


def _pdf_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else f"{v:.2f}"
    return str(v)


# --------------------------------------------------------------------------- #
# xlsx
# --------------------------------------------------------------------------- #
def _xlsx(header, data_rows, totals_row) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Rapor"
    # None/int/float render natively; text cells are formula-guarded.
    ws.append([_safe_cell(c) for c in header])
    for r in data_rows:
        ws.append([_safe_cell(c) for c in r])
    if totals_row:
        ws.append([_safe_cell(c) for c in totals_row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# csv (UTF-8 with BOM for Excel/Türkçe)
# --------------------------------------------------------------------------- #
def _csv(header, data_rows, totals_row) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([_csv_cell(v) for v in header])
    for r in data_rows:
        writer.writerow([_csv_cell(v) for v in r])
    if totals_row:
        writer.writerow([_csv_cell(v) for v in totals_row])
    return (CSV_BOM + buf.getvalue()).encode("utf-8")


# --------------------------------------------------------------------------- #
# pdf (reuse app/services/reports.py ReportLab helpers)
# --------------------------------------------------------------------------- #
def _has_unwindowed_metric(result: dict) -> bool:
    """True if any selected metric is a whole-project snapshot (ignores the date
    window) — drives the "tüm proje, bugüne kadar" note."""
    from app.services.studio.catalog import GRAIN_CASH, GRAIN_COST_LINE, METRICS

    for c in result.get("columns") or []:
        if c.get("kind") != "metric":
            continue
        m = METRICS.get(c["id"])
        if m and m["grain"] not in (GRAIN_COST_LINE, GRAIN_CASH):
            return True
    return False


def _meta_line(result: dict) -> str:
    meta = result.get("meta") or {}
    parts: list[str] = []
    dr = meta.get("date_range") or {}
    if dr.get("from") or dr.get("to"):
        parts.append(f"Dönem: {dr.get('from') or '—'} – {dr.get('to') or '—'}")
    basis = meta.get("basis") or {}
    parts.append(f"Para birimi: {(basis.get('currency') or 'try').upper()}")
    if _has_unwindowed_metric(result):
        parts.append("Bazı metrikler tüm proje, bugüne kadar (tarih aralığından bağımsız)")
    return "  ·  ".join(parts)


def _pdf(header, data_rows, totals_row, title: str, result: dict) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Spacer

    from app.services.reports import _data_table, _render_story, _styles
    from app.utils.format import format_datetime_tr

    s = _styles()  # registers the Türkçe fonts as a side effect
    story = [Paragraph(escape(title or "Rapor"), s["h2"])]
    meta_line = _meta_line(result)
    if meta_line:
        story.append(Paragraph(escape(meta_line), s["note"]))
    story.append(Spacer(1, 6))

    table_rows = [[_pdf_cell(v) for v in header]]
    table_rows += [[_pdf_cell(v) for v in r] for r in data_rows]
    if totals_row:
        table_rows.append([_pdf_cell(v) for v in totals_row])

    columns = result.get("columns") or []
    ncols = len(header) or 1
    col_w = [(17.5 / ncols) * cm] * ncols
    num_cols = tuple(i for i, c in enumerate(columns) if c.get("kind") == "metric")
    story.append(_data_table(table_rows, col_widths=col_w, num_cols=num_cols, header=True))

    generated_at = format_datetime_tr(datetime.now(timezone.utc))
    return _render_story(story, generated_at)


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #
def studio_export(result: dict, fmt: str, title: str) -> Response:
    """Build a downloadable file (pdf/xlsx/csv) from a run_spec result. Read-only.

    Raises ``APIError(422, INVALID_FORMAT)`` for an unknown format (the router also
    guards, so this is defense-in-depth)."""
    header, data_rows, totals_row = _flat_table(result)
    slug = _slug(title)

    if fmt == "xlsx":
        content = _xlsx(header, data_rows, totals_row)
        media, ext = _XLSX_MEDIA, "xlsx"
    elif fmt == "csv":
        content = _csv(header, data_rows, totals_row)
        media, ext = _CSV_MEDIA, "csv"
    elif fmt == "pdf":
        content = _pdf(header, data_rows, totals_row, title, result)
        media, ext = _PDF_MEDIA, "pdf"
    else:
        raise APIError(422, "INVALID_FORMAT", "Geçersiz dışa aktarma biçimi (pdf, xlsx veya csv)")

    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{slug}.{ext}"'},
    )


# --------------------------------------------------------------------------- #
# CR-034 — dashboard (pano) deck export
# --------------------------------------------------------------------------- #
# Excel forbids these in a sheet name and caps it at 31 chars; names must also be
# unique. (Kept separate from studio_export so that path stays byte-for-byte.)
_XLSX_FORBIDDEN = re.compile(r"[\[\]:*?/\\]")


def _ordered_widgets(widgets: list) -> list:
    """Section-grouped, then dashboard-array order: sections appear in first-seen
    order, and within a section widgets keep their array order. Widgets without a
    section group under a stable bucket in array order."""
    buckets: dict = {}
    order: list = []
    for w in widgets or []:
        sec = w.get("section")
        if sec not in buckets:
            buckets[sec] = []
            order.append(sec)
        buckets[sec].append(w)
    ordered: list = []
    for sec in order:
        ordered.extend(buckets[sec])
    return ordered


def _is_renderable(res) -> bool:
    """A widget result carries a table iff it is a dict that is neither empty nor
    the ``{"unavailable": True}`` status sentinel."""
    return isinstance(res, dict) and bool(res) and not res.get("unavailable")


def _sheet_name(title: str, used: set) -> str:
    """Sanitised, ≤31-char, de-duplicated openpyxl sheet name."""
    base = _XLSX_FORBIDDEN.sub(" ", (title or "Sayfa")).strip() or "Sayfa"
    base = base[:31]
    name = base
    i = 1
    used_cf = {u.casefold() for u in used}
    while name.casefold() in used_cf:
        suffix = f" ({i})"
        name = base[: 31 - len(suffix)] + suffix
        i += 1
    return name


def _dashboard_pdf(ordered: list, results: dict, title: str) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Spacer

    from app.services.reports import _data_table, _render_story, _styles
    from app.utils.format import format_datetime_tr

    s = _styles()  # registers the Türkçe fonts as a side effect
    story = [Paragraph(escape(title or "Pano"), s["h2"])]

    last_section = object()  # sentinel so the first (even None) section prints once
    for w in ordered:
        wtype = w.get("type")
        wid = w.get("id")
        section = w.get("section")
        if section and section != last_section:
            story.append(Paragraph(escape(str(section).upper()), s["h3"]))
        last_section = section

        if wtype == "text":
            content = w.get("content")
            if content:
                story.append(Paragraph(escape(str(content)), s["body"]))
                story.append(Spacer(1, 6))
            continue

        res = results.get(wid)
        if isinstance(res, dict) and res.get("unavailable"):
            story.append(Paragraph(f"<b>{escape(w.get('title') or '')}</b>", s["body"]))
            story.append(Paragraph("Bu rapor artık kullanılamıyor", s["note"]))
            story.append(Spacer(1, 6))
            continue
        if not _is_renderable(res):
            continue

        story.append(Paragraph(f"<b>{escape(w.get('title') or '')}</b>", s["body"]))
        header, data_rows, totals_row = _flat_table(res)
        table_rows = [[_pdf_cell(v) for v in header]]
        table_rows += [[_pdf_cell(v) for v in r] for r in data_rows]
        if totals_row:
            table_rows.append([_pdf_cell(v) for v in totals_row])
        columns = res.get("columns") or []
        ncols = len(header) or 1
        col_w = [(17.5 / ncols) * cm] * ncols
        num_cols = tuple(i for i, c in enumerate(columns) if c.get("kind") == "metric")
        story.append(_data_table(table_rows, col_widths=col_w, num_cols=num_cols, header=True))
        story.append(Spacer(1, 10))

    generated_at = format_datetime_tr(datetime.now(timezone.utc))
    return _render_story(story, generated_at)


def _dashboard_xlsx(ordered: list, results: dict) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    default_ws = wb.active
    used_names: set = set()
    sheet_count = 0
    for w in ordered:
        if w.get("type") == "text":
            continue
        res = results.get(w.get("id"))
        if not _is_renderable(res):
            continue
        header, data_rows, totals_row = _flat_table(res)
        name = _sheet_name(w.get("title"), used_names)
        used_names.add(name)
        ws = default_ws if sheet_count == 0 else wb.create_sheet(title=name)
        if sheet_count == 0:
            ws.title = name
        ws.append([_safe_cell(c) for c in header])
        for r in data_rows:
            ws.append([_safe_cell(c) for c in r])
        if totals_row:
            ws.append([_safe_cell(c) for c in totals_row])
        sheet_count += 1

    if sheet_count == 0:
        raise APIError(422, "NO_DATA", "Dışa aktarılacak veri yok")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def studio_export_dashboard(widgets: list, results: dict, title: str, fmt: str) -> Response:
    """Build a dashboard deck file (pdf/xlsx) from already-computed batch results.

    READ-ONLY: consumes ``results`` ({widget_id: run_spec-result-or-status}) and the
    ``widgets`` array (each a dict with id/type/title/section/content), grouped by
    section then dashboard-array order. ``studio_export`` and all its helpers are
    left untouched.

    * ``pdf`` — title + each renderable widget (text → paragraph; unavailable →
      a note; data/report → title + flattened table). No renderable widget ⇒ still a
      title-only PDF (never an error).
    * ``xlsx`` — one sheet per data/report widget that has a result; zero data
      sheets ⇒ ``APIError(422)`` (no empty workbook).
    * ``csv`` — not offered for a multi-widget pano ⇒ ``APIError(422)``.
    """
    ordered = _ordered_widgets(widgets)
    slug = _slug(title)

    if fmt == "pdf":
        content = _dashboard_pdf(ordered, results, title)
        media, ext = _PDF_MEDIA, "pdf"
    elif fmt == "xlsx":
        content = _dashboard_xlsx(ordered, results)
        media, ext = _XLSX_MEDIA, "xlsx"
    elif fmt == "csv":
        raise APIError(422, "INVALID_FORMAT", "Pano CSV olarak dışa aktarılamaz (pdf veya xlsx)")
    else:
        raise APIError(422, "INVALID_FORMAT", "Geçersiz dışa aktarma biçimi (pdf veya xlsx)")

    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{slug}.{ext}"'},
    )
