"""PDF report generation via WeasyPrint (Section 4.9).

All reports are Turkish, use the company colour palette, and include the logo,
title/date, page numbers and a generated-by footer.
"""
from datetime import datetime, timezone

from jinja2 import Template
from sqlalchemy.orm import Session

from app.constants import COST_CATEGORIES
from app.models.company import Company
from app.models.project import Project
from app.services.financials import project_financials
from app.utils.format import format_currency_tr, format_date_tr, format_datetime_tr, format_pct_tr

PRIMARY = "#1B2B4B"
ACCENT = "#F59E0B"
BORDER = "#E2E8F0"

_PROJECT_REPORT = Template(
    """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<style>
  @page { size: A4; margin: 1.6cm 1.4cm 2cm 1.4cm;
    @bottom-center { content: "Sayfa " counter(page) " / " counter(pages); font-size: 9px; color: #64748B; }
    @bottom-left  { content: "Yapı tarafından {{ generated_at }} tarihinde oluşturuldu"; font-size: 8px; color: #94A3B8; }
  }
  body { font-family: Helvetica, Arial, sans-serif; color: #1E293B; font-size: 11px; }
  .header { display: flex; justify-content: space-between; align-items: flex-start;
    border-bottom: 3px solid {{ primary }}; padding-bottom: 10px; margin-bottom: 16px; }
  .logo { max-height: 48px; }
  .company { font-size: 16px; font-weight: 700; color: {{ primary }}; }
  .title-block { text-align: right; }
  h1 { color: {{ primary }}; font-size: 18px; margin: 0; }
  .meta { color: #64748B; font-size: 10px; }
  h2 { color: {{ primary }}; font-size: 13px; border-bottom: 1px solid {{ border }};
    padding-bottom: 4px; margin-top: 18px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th { background: {{ primary }}; color: #fff; text-align: left; padding: 5px 7px; font-size: 10px; }
  td { padding: 4px 7px; border-bottom: 1px solid {{ border }}; font-size: 10px; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .kpis { display: flex; gap: 10px; margin-top: 10px; }
  .kpi { flex: 1; border: 1px solid {{ border }}; border-radius: 6px; padding: 8px; }
  .kpi .label { color: #64748B; font-size: 9px; }
  .kpi .value { font-size: 15px; font-weight: 700; color: {{ primary }}; }
  .rag-red { color: #EF4444; font-weight: 700; }
  .rag-amber { color: #F59E0B; font-weight: 700; }
  .rag-green { color: #10B981; font-weight: 700; }
</style>
</head>
<body>
  <div class="header">
    <div>
      {% if logo_url %}<img class="logo" src="{{ logo_url }}"/>{% endif %}
      <div class="company">{{ company_name }}</div>
    </div>
    <div class="title-block">
      <h1>{{ report_title }}</h1>
      <div class="meta">{{ report_date }}</div>
    </div>
  </div>

  <h2>{{ project_name }} — {{ client_name }}</h2>
  <div class="kpis">
    <div class="kpi"><div class="label">Sözleşme Değeri</div><div class="value">{{ contract_value }}</div></div>
    <div class="kpi"><div class="label">Gerçekleşen Maliyet</div><div class="value">{{ total_actual }}</div></div>
    <div class="kpi"><div class="label">Final Tahmin</div><div class="value">{{ forecast_final }}</div></div>
    <div class="kpi"><div class="label">Kar Marjı</div><div class="value {{ rag_class }}">{{ margin_pct }}</div></div>
  </div>

  <h2>Bütçe & Gerçekleşen (Kategori Bazında)</h2>
  <table>
    <thead><tr>
      <th>Kategori</th><th class="num">Revize Bütçe</th><th class="num">Faturalanan</th>
      <th class="num">Final Tahmin</th><th class="num">Sapma</th><th>Durum</th>
    </tr></thead>
    <tbody>
    {% for c in categories %}
      <tr>
        <td>{{ c.label }}</td>
        <td class="num">{{ c.revised }}</td>
        <td class="num">{{ c.invoiced }}</td>
        <td class="num">{{ c.forecast }}</td>
        <td class="num">{{ c.variance }}</td>
        <td class="rag-{{ c.status }}">{{ c.status_label }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  <h2>Gelir & Tahsilat Özeti</h2>
  <table>
    <tr><td>İşverene Faturalanan</td><td class="num">{{ total_invoiced }}</td></tr>
    <tr><td>Tahsil Edilen</td><td class="num">{{ total_collected }}</td></tr>
    <tr><td>Bekleyen Tahsilat</td><td class="num">{{ total_outstanding }}</td></tr>
    <tr><td>Hakediş Kesintisi</td><td class="num">{{ total_retention }}</td></tr>
    <tr><td>Net Nakit Pozisyonu</td><td class="num">{{ net_cash }}</td></tr>
  </table>
</body>
</html>
"""
)

STATUS_LABELS = {"red": "Kritik", "amber": "Dikkat", "green": "İyi"}


def render_project_report(db: Session, project: Project, company: Company) -> bytes:
    f = project_financials(db, project)
    now = datetime.now(timezone.utc)

    categories = [
        {
            "label": COST_CATEGORIES.get(c["cost_category"], c["cost_category"]),
            "revised": format_currency_tr(c["revised_budget_try"]),
            "invoiced": format_currency_tr(c["invoiced_try"]),
            "forecast": format_currency_tr(c["forecast_final"]),
            "variance": format_currency_tr(c["variance_try"]),
            "status": c["status"],
            "status_label": STATUS_LABELS.get(c["status"], ""),
        }
        for c in f["categories"]
    ]

    html = _PROJECT_REPORT.render(
        primary=PRIMARY, accent=ACCENT, border=BORDER,
        company_name=company.name, logo_url=company.logo_url,
        report_title="Proje Durum Raporu", report_date=format_date_tr(now.date()),
        generated_at=format_datetime_tr(now),
        project_name=project.name, client_name=project.client_name,
        contract_value=format_currency_tr(f["contract_value_try"]),
        total_actual=format_currency_tr(f["total_actual_with_vat_try"]),
        forecast_final=format_currency_tr(f["forecast_final_cost_try"]),
        margin_pct=format_pct_tr(f["margin_pct"]),
        rag_class=f"rag-{f['rag_status']}",
        categories=categories,
        total_invoiced=format_currency_tr(f["total_invoiced_try"]),
        total_collected=format_currency_tr(f["total_collected_try"]),
        total_outstanding=format_currency_tr(f["total_outstanding_try"]),
        total_retention=format_currency_tr(f["total_retention_try"]),
        net_cash=format_currency_tr(f["net_cash_position_try"]),
    )

    from weasyprint import HTML

    return HTML(string=html).write_pdf()
