"""CR-048 — premade decision-grade project reports (Maliyet Detay, Hakediş, Alt
Yüklenici, Nakit Akış) in PDF (Heneka) + Excel (CR-046 engine).

STRICTLY READ-ONLY. **Accuracy is the point (CR-047):** every figure comes from the
EXISTING services — `project_financials` / `sales` / `project_cashflow` / the
subcontractor + retention tools / the studio `run_spec` engine — NEVER fabricated.
Each report is per selected project (the page already requires one), so it is
correctly company-scoped by construction.

The data builders keep no ReportLab import; rendering is isolated in the `_*_pdf`
helpers (mirrors `services/reports.py`). The two PDF+Excel reports (cost, cashflow)
drive their Excel from the SAME builder data shaped into the CR-046 engine's result
shape, so the PDF and Excel can never diverge. The honesty rule holds: a section
renders only when its data is non-empty; otherwise a calm Türkçe note, never a
zero-filled table. `_safe_cell` guards every user string written to Excel.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from app.constants import COST_CATEGORIES, SELL_SIDE_REVENUE_MODELS
from app.models.company import Company
from app.models.project import Project
from app.utils.format import (
    format_currency_tr,
    format_date_tr,
    format_datetime_tr,
    format_pct_tr,
)

D = Decimal
ZERO = D("0")

_TR_MONTHS_SHORT = ["", "Oca", "Şub", "Mar", "Nis", "May", "Haz",
                    "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _money_tr(v) -> str:
    return format_currency_tr(v if v is not None else 0)


def _month_label(month_key: str) -> str:
    """'2026-06' -> 'Haz 26'; a quarter key '2026-Ç2' passes through."""
    if "Ç" in (month_key or ""):
        return month_key
    try:
        y, m = month_key.split("-")
        return f"{_TR_MONTHS_SHORT[int(m)]} {y[2:]}"
    except (ValueError, IndexError):
        return month_key


# --------------------------------------------------------------------------- #
# Studio-engine helpers (authoritative breakdowns the financial services don't
# expose directly — cost by vendor / by month). Project-scoped via a CR-047 filter.
# --------------------------------------------------------------------------- #
def _project_filter(project: Project) -> list:
    return [{"field": "project", "op": "=", "value": str(project.id)}]


def _run(db, company_id, spec):
    from app.services.studio.engine import run_spec
    return run_spec(db, company_id, spec)


# --------------------------------------------------------------------------- #
# CR-046 Excel — shape arbitrary tabular builder data into a run_spec-style result
# so excel_report.build_workbook renders it (Özet KPIs + data sheet + charts) from
# the SAME numbers the PDF used (no divergence, no re-sum).
# --------------------------------------------------------------------------- #
def _kpi_result(kpi_metrics) -> dict:
    """A headerless result whose metric totals ARE the headline figures — fed to a
    ``kpi`` widget so the Excel Özet shows the same KPI cards as the PDF (CR-048).
    ``kpi_metrics`` = [(id, label, value)]."""
    return {
        "columns": [{"id": mid, "label": lbl, "kind": "metric", "type": "currency"}
                    for mid, lbl, _ in kpi_metrics],
        "rows": [],
        "totals": {"metrics": {mid: _num(v) for mid, _, v in kpi_metrics}, "deltas": None},
        "meta": {"date_range": {"from": None, "to": None}, "comparison": None},
    }


def _excel_result(dim, dim_label, metrics, rows, totals, *, dim_type="enum") -> dict:
    """``metrics`` = [(id, label, type)]; ``rows`` = [{dim_value, {id: value}}];
    ``totals`` = {id: value}. Returns a result dict consumed by build_workbook."""
    columns = [{"id": dim, "label": dim_label, "kind": "dimension", "type": dim_type}]
    columns += [{"id": mid, "label": lbl, "kind": "metric", "type": typ} for mid, lbl, typ in metrics]
    out_rows = [
        {"dims": {dim: r["dim"]}, "metrics": {mid: _num(r["vals"].get(mid)) for mid, _, _ in metrics}, "deltas": None}
        for r in rows
    ]
    return {
        "columns": columns,
        "rows": out_rows,
        "totals": {"metrics": {mid: _num(totals.get(mid)) for mid, _, _ in metrics}, "deltas": None},
        "meta": {"date_range": {"from": None, "to": None}, "comparison": None},
    }


# --------------------------------------------------------------------------- #
# Shared PDF doc builder (Heneka furniture — same look as the project report)
# --------------------------------------------------------------------------- #
def _build_pdf(story, doc_title: str, company_name: str, generated_at: str) -> bytes:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate

    from app.services.reports import _project_page_furniture

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=1.7 * cm, bottomMargin=1.6 * cm, leftMargin=1.4 * cm, rightMargin=1.4 * cm,
        title=doc_title,
    )
    paint = _project_page_furniture(company_name, generated_at)
    doc.build(story, onFirstPage=paint, onLaterPages=paint)
    return buf.getvalue()


def _header(company_name: str, title: str, project: Project, extra: str = ""):
    """The header band flowables: company eyebrow + report title + project line."""
    from xml.sax.saxutils import escape

    from reportlab.platypus import Paragraph, Spacer

    from app.services.report_theme import LATO_BOLD, LATO_MEDIUM, MUT, NAVY, s as TS, sect

    story = list(sect(escape((company_name or "Yapı").upper()), escape(title)))
    pl = escape(f"{project.name} — {project.client_name}") if project.client_name else escape(project.name)
    story.append(Paragraph(pl, TS("h2", LATO_BOLD, 13, NAVY, leading=16)))
    meta = " · ".join(x for x in [format_date_tr(datetime.now(timezone.utc).date()), extra] if x)
    if meta:
        story.append(Spacer(1, 2))
        story.append(Paragraph(escape(meta), TS("meta", LATO_MEDIUM, 8.5, MUT)))
    story.append(Spacer(1, 12))
    return story


def _note(text: str):
    """A calm Türkçe note for an empty section (honesty rule)."""
    from xml.sax.saxutils import escape

    from reportlab.platypus import Paragraph

    from app.services.report_theme import LATO_REGULAR, MUT, s as TS
    return Paragraph(escape(text), TS("note", LATO_REGULAR, 9, MUT, leading=13))


# --------------------------------------------------------------------------- #
# 1. Maliyet Detay (cost) — PDF + Excel
# --------------------------------------------------------------------------- #
def build_cost_data(db, project: Project, company: Company) -> dict:
    from app.services.financials import project_financials

    f = project_financials(db, project)
    cats = []
    for c in f["categories"]:
        # Only show categories that actually have budget or spend (honesty rule).
        if not any(_num(c.get(k)) for k in ("revised_budget_try", "invoiced_try", "open_committed_try", "exposure_try")):
            continue
        cats.append({
            "label": COST_CATEGORIES.get(c["cost_category"], c["cost_category"]),
            "revised": c["revised_budget_try"], "actual": c["invoiced_try"],
            "open": c["open_committed_try"], "exposure": c["exposure_try"],
            "forecast": c["forecast_final"], "variance": c["variance_try"], "status": c["status"],
        })

    # Authoritative vendor + monthly breakdowns from the studio engine (project-scoped).
    vrows = _run(db, company.id, {
        "metrics": ["cost_try"], "dimensions": ["vendor"], "filters": _project_filter(project),
        "sort": {"by": "cost_try", "dir": "desc"}, "limit": 10,
    })
    vendors = [{"name": r["dims"].get("vendor") or "—", "amount": r["metrics"].get("cost_try")}
               for r in vrows["rows"] if _num(r["metrics"].get("cost_try"))]

    mrows = _run(db, company.id, {
        "metrics": ["cost_try"], "dimensions": ["month"], "viz": "bar",
        "sort": {"by": "month", "dir": "asc"},  # CR-048 — chronological trend, not by amount
        "filters": _project_filter(project),
    })
    monthly = [{"month": r["dims"].get("month"), "cost": r["metrics"].get("cost_try")} for r in mrows["rows"]]

    # Numeric headline figures for the Excel Özet KPI cards (the PDF uses the formatted
    # strings below; the Excel needs the raw numbers — same source, no divergence).
    kpi_metrics = [
        ("actual", "Gerçekleşen Maliyet", f["total_actual_with_vat_try"]),
        ("exposure", "Maruziyet (CR-023)", f["total_committed_exposure_try"]),
        ("remaining", "Kalan Bütçe", f["remaining_budget_try"]),
        ("forecast", "Tahmini Final", f["forecast_final_cost_try"]),
    ]
    return {
        "company_name": company.name, "project": project,
        "kpis": [(lbl, _money_tr(v)) for _, lbl, v in kpi_metrics],
        "kpi_metrics": kpi_metrics,
        "categories": cats, "vendors": vendors, "monthly": monthly,
    }


def _cost_pdf(d: dict) -> bytes:
    import shutil
    import tempfile

    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer

    from app.services import report_charts as ch
    from app.services.report_theme import chartcard, dtable, kpirow, register_lato_fonts

    register_lato_fonts()
    ch.setup_matplotlib_fonts()
    tmp = tempfile.mkdtemp(prefix="yapi_cost_")
    RAG = {"red": "r", "amber": "a", "green": "g"}
    try:
        story = _header(d["company_name"], "Maliyet Detay Raporu", d["project"])
        story += [kpirow(d["kpis"], colw=4.07), Spacer(1, 14)]

        cats = d["categories"]
        if cats:
            from app.services.report_theme import sect
            story += sect("MALİYET", "Kategori Detayı")
            header = ["Kategori", "Revize Bütçe", "Gerçekleşen", "Açık Taahhüt", "Maruziyet", "Tahmini Final", "Durum"]
            rows = [[c["label"], _money_tr(c["revised"]), _money_tr(c["actual"]), _money_tr(c["open"]),
                     _money_tr(c["exposure"]), _money_tr(c["forecast"]),
                     ("", RAG.get(c["status"], "a"))] for c in cats]
            story += [dtable(header, rows,
                             [3.6 * cm, 2.5 * cm, 2.4 * cm, 2.4 * cm, 2.4 * cm, 2.4 * cm, 1.5 * cm],
                             aligns=[0, 2, 2, 2, 2, 2, 1]), Spacer(1, 10)]
            labels = [_short(c["label"]) for c in cats]
            img = ch.chart_grouped_bar(labels, [("Maruziyet", [_num(c["exposure"]) for c in cats]),
                                                ("Tahmini Final", [_num(c["forecast"]) for c in cats])], tmp)
            story += [chartcard("Kategori Maruziyet / Tahmin", img, 15.6 * cm, 5.2 * cm), Spacer(1, 12)]

        if d["vendors"]:
            from app.services.report_theme import sect
            story += sect("TEDARİKÇİ", "En Yüksek Harcamalı Tedarikçiler")
            vrows = [[v["name"], _money_tr(v["amount"])] for v in d["vendors"]]
            story += [dtable(["Tedarikçi", "Toplam Harcama"], vrows, [12.0 * cm, 5.6 * cm], aligns=[0, 2]), Spacer(1, 12)]

        monthly = [m for m in d["monthly"] if _num(m["cost"])]
        if monthly:
            from app.services.report_theme import sect
            story += sect("TREND", "Aylık Maliyet Trendi")
            img = ch.chart_line([_month_label(m["month"]) for m in monthly],
                                [_num(m["cost"]) for m in monthly], tmp, fill=True)
            story += [chartcard("Aylık Maliyet", img, 15.6 * cm, 5.2 * cm)]

        if not cats and not d["vendors"] and not monthly:
            story.append(_note("Bu projede maliyet kaydı bulunmuyor."))
        return _build_pdf(story, "Yapı Maliyet Raporu", d["company_name"],
                          format_datetime_tr(datetime.now(timezone.utc)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _cost_xlsx(d: dict) -> bytes:
    from app.services.studio.excel_report import build_workbook

    cats = d["categories"]
    metrics = [("actual", "Gerçekleşen", "currency"), ("open", "Açık Taahhüt", "currency"),
               ("exposure", "Maruziyet", "currency"), ("forecast", "Tahmini Final", "currency")]
    cat_rows = [{"dim": c["label"], "vals": {"actual": c["actual"], "open": c["open"],
                                             "exposure": c["exposure"], "forecast": c["forecast"]}} for c in cats]
    cat_totals = {mid: sum(_num(c[mid]) for c in cats) for mid in ("actual", "open", "exposure", "forecast")}
    cat_result = _excel_result("cat", "Kategori", metrics, cat_rows, cat_totals)

    vendors = d["vendors"]
    ven_result = _excel_result(
        "vendor", "Tedarikçi", [("cost", "Toplam Harcama", "currency")],
        [{"dim": v["name"], "vals": {"cost": v["amount"]}} for v in vendors],
        {"cost": sum(_num(v["amount"]) for v in vendors)},
    )

    # The headline KPI cards on the Özet — same figures as the PDF (CR-048).
    widgets = [{"id": "kpi", "type": "kpi", "title": "Özet"}]
    results = {"kpi": _kpi_result(d["kpi_metrics"])}
    if cats:
        # The bar chart references a SLIM (category × Maruziyet) sheet, not a full
        # duplicate of the category detail sheet.
        catbar_result = _excel_result("cat", "Kategori", [("exposure", "Maruziyet", "currency")],
                                      [{"dim": c["label"], "vals": {"exposure": c["exposure"]}} for c in cats],
                                      {"exposure": cat_totals["exposure"]})
        widgets += [{"id": "cat", "type": "report", "title": "Kategori Detayı", "spec": {"viz": "table"}},
                    {"id": "catbar", "type": "chart", "title": "Kategori Maruziyeti", "spec": {"viz": "bar"}}]
        results["cat"] = cat_result
        results["catbar"] = catbar_result
    if vendors:
        widgets += [{"id": "vendor", "type": "report", "title": "Tedarikçi Dökümü", "spec": {"viz": "table"}}]
        results["vendor"] = ven_result
    return build_workbook(widgets, results, title="Maliyet Detay",
                          company=d["company_name"], period=d["project"].name)


def render_cost_report(db, project: Project, company: Company) -> bytes:
    return _cost_pdf(build_cost_data(db, project, company))


def render_cost_xlsx(db, project: Project, company: Company) -> bytes:
    return _cost_xlsx(build_cost_data(db, project, company))


def _short(s: str, n: int = 14) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


# --------------------------------------------------------------------------- #
# 2. Alt Yüklenici (subcontractor) — PDF
# --------------------------------------------------------------------------- #
def build_subcontractor_data(db, project: Project, company: Company) -> dict:
    from app.services import agent_tools

    q = agent_tools.query_subcontractors(db, company.id, project_id=project.id)
    summary, records = q["summary"], q["records"]
    rows = []
    for r in records:
        committed, paid = _num(r["total_committed_try"]), _num(r["paid_to_date_try"])
        rows.append({
            "name": r["name"], "committed": r["total_committed_try"], "paid": r["paid_to_date_try"],
            "remaining": r["remaining_commitment_try"], "retention": r["retention_amount_try"],
            "pct": (paid / committed * 100) if committed else 0.0, "status": r["status"],
        })
    return {
        "company_name": company.name, "project": project, "rows": rows,
        "kpis": [
            ("Taşeron Sayısı", str(summary.get("subcontractor_count", 0))),
            ("Toplam Sözleşme", _money_tr(summary.get("total_committed_try"))),
            ("Ödenen", _money_tr(summary.get("total_paid_try"))),
            ("Kalan", _money_tr(summary.get("total_remaining_try"))),
        ],
    }


def _subcontractor_pdf(d: dict) -> bytes:
    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer

    from app.services.report_theme import dtable, kpirow, register_lato_fonts, sect

    register_lato_fonts()
    story = _header(d["company_name"], "Alt Yüklenici Raporu", d["project"])
    story += [kpirow(d["kpis"], colw=4.07), Spacer(1, 14)]
    rows = d["rows"]
    if rows:
        story += sect("TAŞERON", "Sözleşme & Hakediş Durumu")
        header = ["Taşeron", "Sözleşme", "Ödenen", "Kalan", "% Tamam.", "Kesinti", "Durum"]
        body = [[r["name"], _money_tr(r["committed"]), _money_tr(r["paid"]), _money_tr(r["remaining"]),
                 format_pct_tr(r["pct"]), _money_tr(r["retention"]), r["status"] or "—"] for r in rows]
        story += [dtable(header, body,
                         [3.8 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 1.8 * cm, 2.4 * cm, 2.1 * cm],
                         aligns=[0, 2, 2, 2, 2, 2, 0])]
    else:
        story.append(_note("Bu projede taşeron kaydı bulunmuyor."))
    return _build_pdf(story, "Yapı Alt Yüklenici Raporu", d["company_name"],
                      format_datetime_tr(datetime.now(timezone.utc)))


def render_subcontractor_report(db, project: Project, company: Company) -> bytes:
    return _subcontractor_pdf(build_subcontractor_data(db, project, company))


# --------------------------------------------------------------------------- #
# 3. Nakit Akış (cashflow) — PDF + Excel — FULL project span, quarterly if long
# --------------------------------------------------------------------------- #
_QUARTERLY_THRESHOLD = 24  # months; longer spans aggregate to quarters


def _cashflow_span(db, project: Project, today: date) -> tuple[str, str]:
    """CR-048 — the DATA-RELATIVE full span (start..planned_end ∪ every cost/invoice
    cash date). Shared with the studio engine's all-time cash grain (CR-049) via
    ``financials.cashflow_full_span`` so the premade and the AI-authored cashflow
    cover the same months."""
    from app.services.financials import cashflow_full_span

    return cashflow_full_span(db, project, today=today)


def _cashflow_periods(db, project: Project, today: date) -> list:
    """The project's full-span monthly cashflow (CR-048: data-relative, NOT a trailing
    window), aggregated to quarters when the span is long. Each: {period, in, out, net,
    cum}. Returns [] for a project with no cost/inflow activity (→ a calm note)."""
    from app.services.financials import cashflow_inflows, load_project_inputs, project_cashflow_window

    costs, _, _ = load_project_inputs(db, project)
    # CR-051: the inflow side is revenue-model-aware, so a sell-side project with
    # unit sales (but no client invoices) is NOT treated as empty.
    inflows = cashflow_inflows(db, project, today=today)
    if not costs and not inflows:
        return []
    from_m, to_m = _cashflow_span(db, project, today)
    rows = project_cashflow_window(db, project, from_m, to_m, today=today)["rows"]

    monthly = []
    for r in rows:
        past = r.get("is_past") or r.get("is_current")
        eff_in = r["actual_in_try"] if past else r["planned_in_try"]
        eff_out = r["actual_out_try"] if past else r["planned_out_try"]
        monthly.append({"period": r["month"], "in": D(str(eff_in)), "out": D(str(eff_out)),
                        "net": D(str(r["net_try"])), "cum": D(str(r["cumulative_try"]))})

    if len(monthly) <= _QUARTERLY_THRESHOLD:
        return monthly

    quarters: dict = {}
    order = []
    for m in monthly:
        y, mo = m["period"].split("-")
        qkey = f"{y}-Ç{(int(mo) - 1) // 3 + 1}"
        if qkey not in quarters:
            quarters[qkey] = {"period": qkey, "in": ZERO, "out": ZERO, "net": ZERO, "cum": m["cum"]}
            order.append(qkey)
        quarters[qkey]["in"] += m["in"]
        quarters[qkey]["out"] += m["out"]
        quarters[qkey]["net"] += m["net"]
        quarters[qkey]["cum"] = m["cum"]  # the quarter's last running cumulative
    return [quarters[k] for k in order]


def _cashflow_footnote(project: Project) -> str | None:
    """CR-051/053 — disclose the sell-side cash-in basis (the operator model):
    cash-in comes from the contractor's OWN flat sales (yüklenici) + landowner cash
    contributions, NOT hakediş invoices and NOT the landowner's own (arsa sahibi)
    flat sales. None for hakediş/maliyet_kâr (the default invoice basis needs no note)."""
    if project.revenue_model not in SELL_SIDE_REVENUE_MODELS:
        return None
    return ("Not: Nakit girişleri yüklenicinin kendi daire satışlarından ve arsa sahibi "
            "nakit katkılarından oluşur; arsa sahibinin kendi daire satışları ile hakediş "
            "faturaları dahil değildir. Verilen arsanın bedeli inşaat maliyetine zaten "
            "dahildir (efektif arsa maliyeti olarak ayrıca gösterilir).")


def build_cashflow_data(db, project: Project, company: Company, today: date | None = None) -> dict:
    today = today or date.today()
    periods = _cashflow_periods(db, project, today)
    total_in = sum((p["in"] for p in periods), ZERO)
    total_out = sum((p["out"] for p in periods), ZERO)
    ending = periods[-1]["cum"] if periods else ZERO
    kpi_metrics = [
        ("cash_in", "Toplam Nakit Giriş", total_in),
        ("cash_out", "Toplam Nakit Çıkış", total_out),
        ("net", "Net Nakit", total_in - total_out),
        ("cum", "Kümülatif (Son)", ending),
    ]
    return {
        "company_name": company.name, "project": project, "periods": periods,
        "kpis": [(lbl, _money_tr(v)) for _, lbl, v in kpi_metrics],
        "kpi_metrics": kpi_metrics,
        "footnote": _cashflow_footnote(project),
    }


def _cashflow_pdf(d: dict) -> bytes:
    import shutil
    import tempfile

    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer

    from app.services import report_charts as ch
    from app.services.report_theme import chartcard, dtable, kpirow, register_lato_fonts, sect

    register_lato_fonts()
    ch.setup_matplotlib_fonts()
    tmp = tempfile.mkdtemp(prefix="yapi_cash_")
    try:
        story = _header(d["company_name"], "Nakit Akış Raporu", d["project"])
        story += [kpirow(d["kpis"], colw=4.07), Spacer(1, 14)]
        periods = d["periods"]
        if periods:
            img = ch.chart_line([_month_label(p["period"]) for p in periods],
                                [_num(p["cum"]) for p in periods], tmp, fill=True)
            story += sect("NAKİT", "Kümülatif Nakit Pozisyonu")
            story += [chartcard("Kümülatif Nakit", img, 15.6 * cm, 5.2 * cm), Spacer(1, 12)]
            story += sect("DETAY", "Dönemsel Nakit Akış")
            header = ["Dönem", "Nakit Giriş", "Nakit Çıkış", "Net", "Kümülatif"]
            body = [[_month_label(p["period"]), _money_tr(p["in"]), _money_tr(p["out"]),
                     _money_tr(p["net"]), _money_tr(p["cum"])] for p in periods]
            story += [dtable(header, body, [3.4 * cm, 3.55 * cm, 3.55 * cm, 3.55 * cm, 3.55 * cm],
                             aligns=[0, 2, 2, 2, 2])]
            if d.get("footnote"):
                story += [Spacer(1, 8), _note(d["footnote"])]
        else:
            story.append(_note("Bu projede nakit akış verisi bulunmuyor."))
        return _build_pdf(story, "Yapı Nakit Akış Raporu", d["company_name"],
                          format_datetime_tr(datetime.now(timezone.utc)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _cashflow_xlsx(d: dict) -> bytes:
    from app.services.studio.excel_report import build_workbook

    periods = d["periods"]
    metrics = [("in", "Nakit Giriş", "currency"), ("out", "Nakit Çıkış", "currency"),
               ("net", "Net", "currency"), ("cum", "Kümülatif", "currency")]
    table_rows = [{"dim": _month_label(p["period"]),
                   "vals": {"in": p["in"], "out": p["out"], "net": p["net"], "cum": p["cum"]}} for p in periods]
    table_totals = {"in": sum(_num(p["in"]) for p in periods), "out": sum(_num(p["out"]) for p in periods),
                    "net": sum(_num(p["net"]) for p in periods), "cum": _num(periods[-1]["cum"]) if periods else 0.0}
    table_result = _excel_result("period", "Dönem", metrics, table_rows, table_totals, dim_type="date")
    # A single-metric cumulative series for a clean line chart.
    cum_result = _excel_result("period", "Dönem", [("cum", "Kümülatif", "currency")],
                               [{"dim": _month_label(p["period"]), "vals": {"cum": p["cum"]}} for p in periods],
                               {"cum": _num(periods[-1]["cum"]) if periods else 0.0}, dim_type="date")

    # Headline KPI cards on the Özet — same figures as the PDF (CR-048).
    widgets = [{"id": "kpi", "type": "kpi", "title": "Özet"},
               {"id": "cf", "type": "report", "title": "Dönemsel Nakit Akış", "spec": {"viz": "table"}}]
    results = {"kpi": _kpi_result(d["kpi_metrics"]), "cf": table_result}
    if periods:
        widgets.append({"id": "cum", "type": "chart", "title": "Kümülatif Nakit", "spec": {"viz": "line"}})
        results["cum"] = cum_result
    return build_workbook(widgets, results, title="Nakit Akış",
                          company=d["company_name"], period=d["project"].name)


def render_cashflow_report(db, project: Project, company: Company) -> bytes:
    return _cashflow_pdf(build_cashflow_data(db, project, company))


def render_cashflow_xlsx(db, project: Project, company: Company) -> bytes:
    return _cashflow_xlsx(build_cashflow_data(db, project, company))


# --------------------------------------------------------------------------- #
# 4. Hakediş (invoice) — PDF — REVENUE-MODEL-AWARE (CR-047)
# --------------------------------------------------------------------------- #
def build_invoice_data(db, project: Project, company: Company) -> dict:
    base = {"company_name": company.name, "project": project,
            "sell_side": project.revenue_model in SELL_SIDE_REVENUE_MODELS}
    if base["sell_side"]:
        from app.services import sales

        rc = sales.revenue_cost_totals(db, project)
        units = sales.unit_sales_pnl(db, project)
        land = sales.landowner_rollup(db, project)
        base["mode"] = "sell_side"
        # CR-053 operator model: Toplam Gelir = the contractor's OWN sales (yüklenici)
        # + landowner cash contributions; "Birim Satış Geliri" is that own-sales lane
        # (the breakdown's unit_sales_try), so the three lines reconcile.
        base["kpis"] = [
            ("Toplam Gelir", _money_tr(rc["revenue_try"])),
            ("Birim Satış Geliri (Yüklenici)", _money_tr(rc["revenue_breakdown"]["unit_sales_try"])),
            ("Arsa Sahibi Nakit Katkısı", _money_tr(land.get("total_try"))),
        ]
        # CR-053: the detail rows are the contractor's OWN (yüklenici) sales, so the
        # "Birim Satışları" table reconciles with the "Birim Satış Geliri (Yüklenici)"
        # KPI above it. arsa_sahibi sales are the landowner's flats (not revenue here).
        base["units"] = [
            {"label": u.get("unit_label") or "—", "type": u.get("unit_type") or "—",
             "price": u.get("sale_price_try"), "pnl": u.get("pnl_try")}
            for u in (units.get("allocations") or [])
            if u.get("owner_side") == "yuklenici"
        ]
        base["landowner"] = {"paid": land.get("total_try"), "committed": land.get("committed_total_try"),
                             "remaining": land.get("remaining_try"), "count": land.get("count")}
        return base

    # hakediş / maliyet_kar — real progress-billing invoices.
    from app.services import agent_tools
    from app.services.financials import project_financials

    f = project_financials(db, project)
    inv = agent_tools.query_client_invoices(db, company.id, project_id=project.id)
    contract = _num(f["contract_value_try"])
    invoiced = _num(f["total_invoiced_try"])
    base["mode"] = "hakedis"
    base["kpis"] = [
        ("İşverene Faturalanan", _money_tr(f["total_invoiced_try"])),
        ("Tahsil Edilen", _money_tr(f["total_collected_try"])),
        ("Bekleyen Tahsilat", _money_tr(f["total_outstanding_try"])),
        ("Hakediş Kesintisi", _money_tr(f["total_retention_try"])),
    ]
    base["billing_vs_contract"] = (invoiced / contract * 100) if contract else None
    base["contract_value"] = f["contract_value_try"]
    base["invoices"] = [
        {"number": r["invoice_number"], "date": r["invoice_date"], "amount": r["total_with_vat_try"],
         "outstanding": r["outstanding_try"], "status": r["payment_status"]}
        for r in inv["records"]
    ]
    return base


def _invoice_pdf(d: dict) -> bytes:
    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer

    from app.services.report_theme import dtable, kpirow, register_lato_fonts, sect

    register_lato_fonts()
    story = _header(d["company_name"], "Hakediş Raporu", d["project"])

    if d["sell_side"]:
        story.append(_note(
            "Bu proje kat karşılığı / yap-sat modelinde — klasik hakediş bulunmuyor. "
            "Aşağıda satış geliri görünümü yer alır (detaylı satışlar için Satışlar sayfasına bakın)."))
        story.append(Spacer(1, 10))
        story += [kpirow(d["kpis"], colw=5.4), Spacer(1, 14)]
        units = d.get("units") or []
        if units:
            story += sect("SATIŞ", "Birim Satışları")
            header = ["Birim", "Tip", "Satış Fiyatı", "Kâr/Zarar"]
            body = [[u["label"], u["type"], _money_tr(u["price"]), _money_tr(u["pnl"])] for u in units]
            story += [dtable(header, body, [4.6 * cm, 3.0 * cm, 5.0 * cm, 5.0 * cm], aligns=[0, 0, 2, 2]), Spacer(1, 12)]
        land = d.get("landowner") or {}
        if _num(land.get("paid")) or _num(land.get("committed")):
            story += sect("ARSA SAHİBİ", "Arsa Sahibi Ödemeleri")
            lrows = [["Taahhüt", _money_tr(land.get("committed"))], ["Ödenen", _money_tr(land.get("paid"))],
                     ["Kalan", _money_tr(land.get("remaining"))]]
            story += [dtable(["Kalem", "Tutar"], lrows, [12.0 * cm, 5.6 * cm], aligns=[0, 2])]
        return _build_pdf(story, "Yapı Hakediş Raporu", d["company_name"],
                          format_datetime_tr(datetime.now(timezone.utc)))

    # hakediş mode
    story += [kpirow(d["kpis"], colw=4.07), Spacer(1, 14)]
    bvc = d.get("billing_vs_contract")
    if bvc is not None:
        story += sect("ÖZET", "Hakediş / Sözleşme")
        story += [dtable(["Kalem", "Tutar"],
                         [["Sözleşme Değeri", _money_tr(d.get("contract_value"))],
                          ["Faturalanan / Sözleşme", format_pct_tr(bvc)]],
                         [12.0 * cm, 5.6 * cm], aligns=[0, 2]), Spacer(1, 12)]
    invoices = d.get("invoices") or []
    if invoices:
        story += sect("HAKEDİŞ", "İşveren Faturaları")
        header = ["Fatura No", "Tarih", "Tutar (KDV dahil)", "Bekleyen", "Durum"]
        body = [[i["number"], i["date"] or "—", _money_tr(i["amount"]), _money_tr(i["outstanding"]),
                 i["status"] or "—"] for i in invoices]
        story += [dtable(header, body, [3.6 * cm, 2.6 * cm, 4.2 * cm, 3.6 * cm, 3.0 * cm], aligns=[0, 0, 2, 2, 0])]
    else:
        story.append(_note("Bu projede hakediş faturası bulunmuyor."))
    return _build_pdf(story, "Yapı Hakediş Raporu", d["company_name"],
                      format_datetime_tr(datetime.now(timezone.utc)))


def render_invoice_report(db, project: Project, company: Company) -> bytes:
    return _invoice_pdf(build_invoice_data(db, project, company))
