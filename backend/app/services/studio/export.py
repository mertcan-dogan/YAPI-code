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
def _csv_cell(v) -> str:
    return "" if v is None else str(v)


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
    ws.append(header)
    for r in data_rows:
        ws.append(list(r))  # None / int / float / str all render natively
    if totals_row:
        ws.append(list(totals_row))
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
