"""CR-037 §6 — Studio exports now embed real charts (report_charts toolkit).

Proves the spec §6 Studio-chart acceptance gates:

* a ``line`` (date-dimension) report PDF embeds a chart image (an /Image XObject)
  AND is materially LARGER than the same result exported as a ``table`` (no chart);
* the same holds for a ``bar`` report;
* a dashboard deck PDF with a kpi + a chart + a table widget renders every widget
  without error and embeds the chart (/Image);
* the xlsx / csv byte-paths are UNCHANGED by the new ``viz`` argument (the chart
  is a PDF-only concern);
* read-only: building results + exporting (report PDF and dashboard PDF) writes
  zero business rows.

Runs on the SQLite ``seed`` / ``db`` fixtures (conftest). ``run_spec`` /
``studio_export`` / ``studio_export_dashboard`` are exercised at the service layer
so the test owns the exact ``viz`` / widget shapes. No network; matplotlib on Agg.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.services.studio.engine import run_spec
from app.services.studio.export import studio_export, studio_export_dashboard

D = Decimal


# --------------------------------------------------------------------------- #
# Seed helpers
# --------------------------------------------------------------------------- #
def _cost(db, p, amount, uid, *, d, cat="material_steel"):
    amt = D(str(amount))
    db.add(CostEntry(
        project_id=p.id, company_id=p.company_id, entry_date=d, cost_category=cat,
        amount_try=amt, vat_rate=D("0"), vat_amount_try=D("0"), total_with_vat_try=amt,
        payment_status="unpaid", entry_type="actual", created_by=uid,
    ))
    db.commit()


def _seed_months(db, seed, label="a"):
    """Costs spanning several months so a month-dimension series has >1 point."""
    p = seed[label]["project"]
    uid = seed[label]["users"][ROLE_DIRECTOR].id
    _cost(db, p, "100000", uid, d=date(2026, 1, 10))
    _cost(db, p, "70000", uid, d=date(2026, 2, 10))
    _cost(db, p, "50000", uid, d=date(2026, 3, 10))
    return p, seed[label]["company"].id


def _count(db, model) -> int:
    db.expire_all()
    return db.execute(select(func.count()).select_from(model)).scalar_one()


LINE_SPEC = {"metrics": ["cost_try"], "dimensions": ["month"], "viz": "line"}
BAR_SPEC = {"metrics": ["cost_try"], "dimensions": ["month"], "viz": "bar"}


# --------------------------------------------------------------------------- #
# 1) line report PDF embeds a chart and is larger than the table-only export
# --------------------------------------------------------------------------- #
def test_studio_line_report_pdf_embeds_chart(db, seed):
    p, cid = _seed_months(db, seed)
    result = run_spec(db, cid, LINE_SPEC)
    assert result.get("series"), "viz=line must produce a series"
    assert any(s["points"] for s in result["series"])

    chart_pdf = studio_export(result, "pdf", "Grafik Rapor", viz="line").body
    table_pdf = studio_export(result, "pdf", "Grafik Rapor", viz="table").body

    assert chart_pdf[:4] == b"%PDF"
    assert table_pdf[:4] == b"%PDF"
    # An embedded PNG → an /Image XObject ("/Subtype /Image") in the PDF, present
    # only for the chart export. (Plain "/Image" matches ReportLab's default
    # /ImageB /ImageC /ImageI ProcSet on every page, so it is NOT a reliable signal.)
    assert b"/Subtype /Image" in chart_pdf
    assert b"/Subtype /Image" not in table_pdf
    # The chart export is materially larger than the table-only one (robust fallback).
    assert len(chart_pdf) > len(table_pdf) + 1000


# --------------------------------------------------------------------------- #
# 2) bar report PDF embeds a chart and is larger than the table-only export
# --------------------------------------------------------------------------- #
def test_studio_bar_report_pdf_embeds_chart(db, seed):
    p, cid = _seed_months(db, seed)
    result = run_spec(db, cid, BAR_SPEC)
    assert result.get("series")

    chart_pdf = studio_export(result, "pdf", "Çubuk Rapor", viz="bar").body
    table_pdf = studio_export(result, "pdf", "Çubuk Rapor", viz="table").body

    assert chart_pdf[:4] == b"%PDF"
    assert b"/Subtype /Image" in chart_pdf
    assert b"/Subtype /Image" not in table_pdf
    assert len(chart_pdf) > len(table_pdf) + 1000


# --------------------------------------------------------------------------- #
# 3) viz does NOT touch the xlsx / csv byte-paths (PDF-only feature)
# --------------------------------------------------------------------------- #
def test_viz_does_not_change_xlsx_csv_bytes(db, seed):
    p, cid = _seed_months(db, seed)
    result = run_spec(db, cid, LINE_SPEC)

    for fmt in ("xlsx", "csv"):
        none = studio_export(result, fmt, "Eşit", viz=None).body
        line = studio_export(result, fmt, "Eşit", viz="line").body
        assert none == line, f"{fmt} bytes changed with viz"
    # And the magic bytes are still the expected containers.
    assert studio_export(result, "xlsx", "Eşit", viz="line").body[:2] == b"PK"
    assert studio_export(result, "csv", "Eşit", viz="line").body[:3] == b"\xef\xbb\xbf"


# --------------------------------------------------------------------------- #
# 4) dashboard deck PDF — kpi + chart + table widgets, chart embedded
# --------------------------------------------------------------------------- #
def test_dashboard_pdf_renders_kpi_chart_table(db, seed):
    p, cid = _seed_months(db, seed)

    widgets = [
        {"id": "k1", "type": "kpi", "title": "Toplam Maliyet",
         "spec": {"metrics": ["cost_try"], "viz": "kpi"}},
        {"id": "c1", "type": "chart", "title": "Aylık Maliyet",
         "spec": {"metrics": ["cost_try"], "dimensions": ["month"], "viz": "line"}},
        {"id": "t1", "type": "table", "title": "Proje Maliyeti",
         "spec": {"metrics": ["cost_try"], "dimensions": ["project"], "viz": "table"}},
    ]
    results = {w["id"]: run_spec(db, cid, w["spec"]) for w in widgets}
    assert results["c1"].get("series"), "chart widget result must carry a series"

    resp = studio_export_dashboard(widgets, results, "Karma Pano", "pdf")
    body = resp.body
    assert body[:4] == b"%PDF"
    assert len(body) > 1000
    assert b"/Subtype /Image" in body  # the chart widget produced an embedded image


# --------------------------------------------------------------------------- #
# 5) Read-only — building results + exporting writes zero business rows
# --------------------------------------------------------------------------- #
def test_studio_exports_are_read_only(db, seed):
    p, cid = _seed_months(db, seed)
    cost_before = _count(db, CostEntry)
    inv_before = _count(db, ClientInvoice)

    result = run_spec(db, cid, LINE_SPEC)
    studio_export(result, "pdf", "Grafik", viz="line")

    widgets = [
        {"id": "c1", "type": "chart", "title": "Aylık",
         "spec": {"metrics": ["cost_try"], "dimensions": ["month"], "viz": "line"}},
    ]
    dash_results = {"c1": run_spec(db, cid, widgets[0]["spec"])}
    studio_export_dashboard(widgets, dash_results, "Pano", "pdf")

    assert _count(db, CostEntry) == cost_before
    assert _count(db, ClientInvoice) == inv_before
