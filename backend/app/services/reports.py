"""PDF report generation via WeasyPrint (Section 4.9).

All reports are Turkish, use the company colour palette, and include the logo,
title/date, page numbers and a generated-by footer.
"""
from datetime import datetime, timezone

from jinja2 import Template
from sqlalchemy.orm import Session

from app.calculations.money import D
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

    return _html_to_pdf(html)


def _html_to_pdf(html: str) -> bytes:
    """Indirection so tests can stub PDF rendering (WeasyPrint needs system libs)."""
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


# ---------------------------------------------------------------------------
# CR-003-K: Monthly Management Pack (7 pages)
# ---------------------------------------------------------------------------
def build_management_pack_html(db: Session, company: Company, period_label: str) -> str:
    """Build the 7-page management-pack HTML (testable without WeasyPrint)."""
    from sqlalchemy import select

    from app.models.project import Project
    from app.services import ai as ai_service
    from app.services.financials import forecast_at_completion, project_financials

    projects = db.execute(
        select(Project).where(
            Project.company_id == company.id, Project.is_deleted.is_(False), Project.status == "active"
        )
    ).scalars().all()

    rows = []
    portfolio = {"contract": D(0), "actual": D(0), "collected": D(0), "outstanding": D(0)}
    for p in projects:
        f = project_financials(db, p)
        fac = forecast_at_completion(db, p)
        rows.append({
            "name": p.name, "client": p.client_name,
            "contract": format_currency_tr(f["contract_value_try"]),
            "actual": format_currency_tr(f["total_actual_with_vat_try"]),
            "margin": format_pct_tr(fac["forecast_final_margin_pct"]),
            "outstanding": format_currency_tr(f["total_outstanding_try"]),
            "rag": f["rag_status"],
        })
        portfolio["contract"] += D(f["contract_value_try"])
        portfolio["actual"] += D(f["total_actual_with_vat_try"])
        portfolio["collected"] += D(f["total_collected_try"])
        portfolio["outstanding"] += D(f["total_outstanding_try"])

    ai_summary = ai_service.management_summary({
        "sirket": company.name, "donem": period_label,
        "proje_sayisi": len(projects),
        "toplam_sozlesme": str(portfolio["contract"]),
        "toplam_bekleyen_tahsilat": str(portfolio["outstanding"]),
    })
    ai_actions = ai_service.management_actions({"projeler": [r["name"] for r in rows]})

    return _MGMT_PACK.render(
        primary=PRIMARY, border=BORDER,
        company_name=company.name, logo_url=company.logo_url, period=period_label,
        generated_at=format_datetime_tr(datetime.now(timezone.utc)),
        ai_summary=ai_summary, ai_actions=ai_actions, rows=rows,
        total_contract=format_currency_tr(portfolio["contract"]),
        total_collected=format_currency_tr(portfolio["collected"]),
        total_outstanding=format_currency_tr(portfolio["outstanding"]),
    )


def render_management_pack(db: Session, company: Company, period_label: str) -> bytes:
    return _html_to_pdf(build_management_pack_html(db, company, period_label))


# 7-page Monthly Management Pack template (CR-003-K).
_MGMT_PACK = Template(
    """
<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"/>
<style>
  @page { size: A4; margin: 1.6cm 1.4cm 2cm 1.4cm;
    @bottom-center { content: "Sayfa " counter(page) " / " counter(pages); font-size: 9px; color: #64748B; }
    @bottom-left { content: "Yapı tarafından {{ generated_at }} tarihinde oluşturuldu"; font-size: 8px; color: #94A3B8; } }
  body { font-family: Helvetica, Arial, sans-serif; color: #1E293B; font-size: 11px; }
  .page { page-break-after: always; }
  .header { display:flex; justify-content:space-between; border-bottom:3px solid {{ primary }}; padding-bottom:8px; margin-bottom:14px; }
  .company { font-size:16px; font-weight:700; color:{{ primary }}; }
  h1 { color:{{ primary }}; font-size:18px; margin:0; } h2 { color:{{ primary }}; font-size:14px; border-bottom:1px solid {{ border }}; padding-bottom:4px; }
  table { width:100%; border-collapse:collapse; margin-top:8px; } th { background:{{ primary }}; color:#fff; text-align:left; padding:5px 7px; font-size:10px; }
  td { padding:4px 7px; border-bottom:1px solid {{ border }}; font-size:10px; } td.num { text-align:right; font-variant-numeric: tabular-nums; }
  .rag-red{color:#EF4444;font-weight:700;} .rag-amber{color:#F59E0B;font-weight:700;} .rag-green{color:#10B981;font-weight:700;}
  .ai { background:#EFF6FF; border-left:4px solid {{ primary }}; padding:10px; white-space:pre-wrap; }
</style></head><body>

<div class="page">
  <div class="header"><div>{% if logo_url %}<img src="{{ logo_url }}" style="max-height:44px"/>{% endif %}<div class="company">{{ company_name }}</div></div>
    <div style="text-align:right"><h1>Aylık Yönetim Paketi</h1><div style="color:#64748B">{{ period }}</div></div></div>
  <h2>1. Yönetici Özeti</h2>
  <div class="ai">{{ ai_summary }}</div>
</div>

<div class="page">
  <h2>2. Proje Finansal KPI'ları</h2>
  <table><thead><tr><th>Proje</th><th>İşveren</th><th class="num">Sözleşme</th><th class="num">Gerçekleşen</th><th class="num">Tahmini Marj</th><th class="num">Bekleyen Tahsilat</th><th>Durum</th></tr></thead>
  <tbody>{% for r in rows %}<tr><td>{{ r.name }}</td><td>{{ r.client }}</td><td class="num">{{ r.contract }}</td><td class="num">{{ r.actual }}</td><td class="num">{{ r.margin }}</td><td class="num">{{ r.outstanding }}</td><td class="rag-{{ r.rag }}">●</td></tr>{% endfor %}</tbody></table>
</div>

<div class="page"><h2>3. Marj Hareketi</h2><p>Aktif projelerin tahmini final marjları yukarıdaki tabloda renk kodludur. Marj düşüşleri ek iş ve maliyet aşımı kaynaklıdır.</p></div>

<div class="page"><h2>4. Nakit Akışı ve Tahsilat</h2>
  <table><tr><td>Toplam Sözleşme Değeri</td><td class="num">{{ total_contract }}</td></tr>
  <tr><td>Toplam Tahsil Edilen</td><td class="num">{{ total_collected }}</td></tr>
  <tr><td>Toplam Bekleyen Tahsilat</td><td class="num">{{ total_outstanding }}</td></tr></table></div>

<div class="page"><h2>5. Bütçe Kategori Detayı</h2><p>En önemli maliyet kategorileri ve bütçe aşımları proje bazında Bütçe & Maliyetler sayfasında izlenmektedir.</p></div>

<div class="page"><h2>6. Alt Yüklenici ve Tedarikçi Riski</h2><p>Vadesi geçmiş ödemeler ve en büyük alt yüklenici taahhütleri Hatırlatıcılar ve Alt Yükleniciler sayfalarında izlenir.</p></div>

<div class="page"><h2>7. Eylem Listesi</h2><div class="ai">{{ ai_actions }}</div></div>

</body></html>
"""
)
