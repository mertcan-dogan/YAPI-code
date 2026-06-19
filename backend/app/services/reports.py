"""PDF report generation via ReportLab (Section 4.9, CR-004-A).

Switched from WeasyPrint to ReportLab so reports render on Windows without the
GTK/Pango/Cairo system libraries WeasyPrint requires. The Turkish content, colour
palette, company logo, title/date, page numbers and generated-by footer are
preserved; the monthly management pack keeps its 7-page structure.

Data gathering (``build_*_data``) is kept free of ReportLab imports so it stays
unit-testable, and the actual rendering lives in ``_*_pdf`` helpers that tests can
stub. The AI summary text still comes from the same Claude API calls.
"""
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.calculations.money import D
from app.constants import COST_CATEGORIES
from app.models.company import Company
from app.models.project import Project
from app.services.financials import project_financials
from app.utils.format import format_currency_tr, format_date_tr, format_datetime_tr, format_pct_tr

# CR-005-A: Türkçe karakterleri (ş, ğ, ı, İ, ü, ö, ç) destekleyen Unicode fontlar.
# ReportLab'ın varsayılan Helvetica/Times fontları Latin-1 ile sınırlı olduğundan
# Türkçe karakterler PDF'te ■ olarak görünüyordu. Bu üç font (app/fonts/) ile
# tüm metin/tablo/grafiklerde Türkçe karakterler doğru render edilir.
FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")
FONT_NORMAL = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"
FONT_OBLIQUE = "DejaVuSans-Oblique"

_fonts_registered = False


def register_turkish_fonts():
    """Register the Türkçe-capable TTF fonts with ReportLab (idempotent)."""
    global _fonts_registered
    if _fonts_registered:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont(FONT_NORMAL, os.path.join(FONTS_DIR, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, os.path.join(FONTS_DIR, "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_OBLIQUE, os.path.join(FONTS_DIR, "DejaVuSans-Oblique.ttf")))
    # Map the bold/italic variants so <b>/<i> inline markup and bold styles resolve.
    from reportlab.pdfbase.pdfmetrics import registerFontFamily

    registerFontFamily(
        FONT_NORMAL, normal=FONT_NORMAL, bold=FONT_BOLD,
        italic=FONT_OBLIQUE, boldItalic=FONT_BOLD,
    )
    _fonts_registered = True


# Yapı colour palette (unchanged from the WeasyPrint version).
PRIMARY = "#1B2B4B"
ACCENT = "#F59E0B"
BORDER = "#E2E8F0"
MUTED = "#64748B"

STATUS_LABELS = {"red": "Kritik", "amber": "Dikkat", "green": "İyi"}
RAG_COLORS = {"red": "#EF4444", "amber": "#F59E0B", "green": "#10B981"}
# CR-006-A: light tints used as cell BACKGROUND for colour-coded table cells.
RAG_TINTS = {"red": "#FEE2E2", "amber": "#FEF3C7", "green": "#DCFCE7", "gray": "#F1F5F9"}
NAVY = "#1E3A5F"   # CR-006-A cover/header band colour (per spec)

# CR-004-F: every AI-written output carries this disclaimer; the management pack
# embeds it in the PDF footer because pages 1 and 7 are AI-generated.
AI_DISCLAIMER = (
    "Bu içerik yapay zeka tarafından oluşturulmuştur ve hatalar içerebilir. "
    "Önemli finansal kararlar almadan önce lütfen doğrulayın."
)

# The seven management-pack sections (CR-003-K). Kept as data so the structure is
# verifiable without rendering a PDF.
SECTION_TITLES = [
    "1. Yönetici Özeti",
    "2. Proje Finansal KPI'ları",
    "3. Marj Hareketi",
    "4. Nakit Akışı ve Tahsilat",
    "5. Bütçe Kategori Detayı",
    "6. Alt Yüklenici ve Tedarikçi Riski",
    "7. Eylem Listesi",
]


# ---------------------------------------------------------------------------
# Project status report
# ---------------------------------------------------------------------------
def build_project_report_data(db: Session, project: Project, company: Company) -> dict:
    """Gather everything the project report needs (no ReportLab import)."""
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
    return {
        "company_name": company.name,
        "logo_url": company.logo_url,
        "report_title": "Proje Durum Raporu",
        "report_date": format_date_tr(now.date()),
        "generated_at": format_datetime_tr(now),
        "project_name": project.name,
        "client_name": project.client_name,
        "contract_value": format_currency_tr(f["contract_value_try"]),
        "total_actual": format_currency_tr(f["total_actual_with_vat_try"]),
        "forecast_final": format_currency_tr(f["forecast_final_cost_try"]),
        "margin_pct": format_pct_tr(f["margin_pct"]),
        "rag_status": f["rag_status"],
        "categories": categories,
        "total_invoiced": format_currency_tr(f["total_invoiced_try"]),
        "total_collected": format_currency_tr(f["total_collected_try"]),
        "total_outstanding": format_currency_tr(f["total_outstanding_try"]),
        "total_retention": format_currency_tr(f["total_retention_try"]),
        "net_cash": format_currency_tr(f["net_cash_position_try"]),
    }


def render_project_report(db: Session, project: Project, company: Company) -> bytes:
    return _project_report_pdf(build_project_report_data(db, project, company))


# ---------------------------------------------------------------------------
# Monthly Management Pack (CR-003-K) — 7 pages
# ---------------------------------------------------------------------------
def build_management_pack_data(db: Session, company: Company, period_label: str) -> dict:
    """Gather the management-pack data (no ReportLab import; unit-testable).

    CR-006-A: every section now carries real, project-specific data — margin
    movement per project (§3), an aggregated budget table (§5), subcontractor /
    overdue-payment risk (§6) and a dynamically-built action list (§7). The
    cover-page KPIs and the existing chart datasets are produced here too so the
    renderer stays a pure formatting layer.
    """
    from datetime import date

    from app.services import ai as ai_service
    from app.services.financials import forecast_at_completion, project_cashflow

    projects = _active_projects(db, company)

    today = date.today()
    rows = []
    margin_movement = []              # §3 — per-project category movement
    collection_rows = []              # §4 — per-project collection / aging
    portfolio = {"contract": D(0), "actual": D(0), "collected": D(0),
                 "invoiced": D(0), "outstanding": D(0)}
    # CR-005-A chart accumulators.
    margin_chart = []                 # Grafik 1 — per-project target vs forecast margin
    cat_totals: dict[str, dict] = {}  # §5 + Grafik 2 — budget usage by category
    cash_in: dict[str, object] = {}   # Grafik 3 — monthly income (last 6 months)
    cash_out: dict[str, object] = {}  # Grafik 3 — monthly expense (last 6 months)
    anchor = _parse_period_anchor(period_label)
    worst_rag = "green"
    for p in projects:
        f = project_financials(db, p)
        fac = forecast_at_completion(db, p)
        target_margin = float(p.target_margin_pct) if p.target_margin_pct is not None else 0.0
        forecast_margin = float(fac["forecast_final_margin_pct"])
        completion = float(f["completion_pct"])
        rows.append({
            "name": p.name,
            "client": p.client_name,
            "contract": format_currency_tr(f["contract_value_try"]),
            "actual": format_currency_tr(f["total_actual_with_vat_try"]),
            "completion": format_pct_tr(f["completion_pct"]),
            "target_margin": format_pct_tr(target_margin),
            "margin": format_pct_tr(fac["forecast_final_margin_pct"]),
            "margin_value": round(forecast_margin, 1),
            "outstanding": format_currency_tr(f["total_outstanding_try"]),
            "outstanding_high": D(f["total_outstanding_try"]) > D(f["contract_value_try"]) * D("0.20"),
            "rag": f["rag_status"],
        })
        worst_rag = _worse_rag(worst_rag, f["rag_status"])
        margin_chart.append({
            "name": p.name,
            "target_pct": round(target_margin, 1),
            "forecast_pct": round(forecast_margin, 1),
        })
        # §3 — margin movement: per-category variance, top 5 by |variance|.
        cats = [c for c in f["categories"] if D(c["revised_budget_try"]) > 0 or D(c["invoiced_try"]) > 0]
        cats_sorted = sorted(cats, key=lambda c: abs(D(c["variance_try"])), reverse=True)
        movement_cats = [{
            "label": COST_CATEGORIES.get(c["cost_category"], c["cost_category"]),
            "original": format_currency_tr(c["original_budget_try"]),
            "revised": format_currency_tr(c["revised_budget_try"]),
            "invoiced": format_currency_tr(c["invoiced_try"]),
            "variance": format_currency_tr(c["variance_try"]),
            "pct_spent": format_pct_tr(c["pct_spent"]),
            "status": c["status"],
        } for c in cats_sorted[:5]]
        # Dynamic driver text — the 2 categories with the largest positive overrun.
        overruns = sorted(
            (c for c in cats if D(c["variance_try"]) > 0),
            key=lambda c: D(c["variance_try"]), reverse=True,
        )[:2]
        if overruns:
            drivers = ", ".join(COST_CATEGORIES.get(c["cost_category"], c["cost_category"]) for c in overruns)
            driver_text = f"Marj düşüşünün başlıca nedenleri: {drivers}."
        else:
            driver_text = "Bu projede bütçe aşımı kaynaklı marj düşüşü tespit edilmemiştir."
        margin_movement.append({
            "name": p.name,
            "final_margin": format_pct_tr(fac["forecast_final_margin_pct"]),
            "final_margin_rag": _margin_rag(forecast_margin),
            "categories": movement_cats,
            "driver_text": driver_text,
        })
        # §4 — per-project collection / aging.
        collection_rows.append({
            "name": p.name,
            "invoiced": format_currency_tr(f["total_invoiced_try"]),
            "collected": format_currency_tr(f["total_collected_try"]),
            "outstanding": format_currency_tr(f["total_outstanding_try"]),
            "overdue_days": f["max_overdue_days"],
            "overdue": f["max_overdue_days"] >= 30,
        })
        # §5 + Grafik 2 — aggregate revised/committed/invoiced per cost category.
        for c in f["categories"]:
            key = c["cost_category"]
            t = cat_totals.setdefault(key, {"revised": D(0), "committed": D(0), "invoiced": D(0)})
            t["revised"] += D(c["revised_budget_try"])
            t["committed"] += D(c["committed_try"])
            t["invoiced"] += D(c["invoiced_try"])
        # Cash flow: aggregate effective monthly in/out over the trailing 6 months.
        for m in project_cashflow(db, p, today=anchor):
            if not (m["is_past"] or m["is_current"]):
                continue
            cash_in[m["month"]] = D(cash_in.get(m["month"], D(0))) + D(m["actual_in_try"])
            cash_out[m["month"]] = D(cash_out.get(m["month"], D(0))) + D(m["actual_out_try"])
        portfolio["contract"] += D(f["contract_value_try"])
        portfolio["actual"] += D(f["total_actual_with_vat_try"])
        portfolio["collected"] += D(f["total_collected_try"])
        portfolio["invoiced"] += D(f["total_invoiced_try"])
        portfolio["outstanding"] += D(f["total_outstanding_try"])

    # §5 — budget summary table over every category that has activity (sorted by % spent).
    budget_summary = []
    budget_chart = []
    for key, t in cat_totals.items():
        revised = t["revised"]
        committed = t["committed"]
        invoiced = t["invoiced"]
        if revised <= 0 and invoiced <= 0:
            continue
        spent_pct = float(invoiced / revised * 100) if revised > 0 else 0.0
        budget_summary.append({
            "label": COST_CATEGORIES.get(key, key),
            "revised": format_currency_tr(revised),
            "committed": format_currency_tr(committed),
            "invoiced": format_currency_tr(invoiced),
            "remaining": format_currency_tr(revised - committed),
            "pct_spent": format_pct_tr(spent_pct),
            "pct_value": round(spent_pct, 1),
            "revised_d": revised,
        })
        if revised > 0:
            budget_chart.append({"label": COST_CATEGORIES.get(key, key), "spent_pct": round(spent_pct, 1)})
    budget_summary.sort(key=lambda x: x["pct_value"], reverse=True)
    budget_chart.sort(key=lambda x: x["spent_pct"], reverse=True)
    budget_chart = budget_chart[:8]
    budget_total = {
        "revised": format_currency_tr(sum((D(b["revised_d"]) for b in budget_summary), D(0))),
    }

    # §6 — subcontractor & supplier risk.
    overdue_payments = _company_overdue_payments(db, company, today)
    subcontractor_commitments = _subcontractor_commitments(db, company)

    # Grafik 3 — last 6 months of income vs expense, chronological.
    cash_months = sorted(set(cash_in) | set(cash_out))[-6:]
    cashflow_chart = [
        {
            "month": mk,
            "income": float(cash_in.get(mk, D(0))),
            "expense": float(cash_out.get(mk, D(0))),
        }
        for mk in cash_months
    ]

    ai_summary = ai_service.management_summary({
        "sirket": company.name,
        "donem": period_label,
        "proje_sayisi": len(projects),
        "toplam_sozlesme": str(portfolio["contract"]),
        "toplam_bekleyen_tahsilat": str(portfolio["outstanding"]),
    })
    ai_actions = ai_service.management_actions({"projeler": [r["name"] for r in rows]})

    # §7 — dynamic, project-specific action list (no generic advice).
    action_items = _build_action_items(
        rows, margin_movement, overdue_payments, budget_summary, ai_actions, period_label
    )

    # Cover-page KPIs (real portfolio data).
    cover_kpis = {
        "active_projects": str(len(projects)),
        "total_contract": format_currency_tr(portfolio["contract"]),
        "total_outstanding": format_currency_tr(portfolio["outstanding"]),
        "risk_level": _RISK_LABELS[worst_rag],
        "risk_rag": worst_rag,
    }

    return {
        "company_name": company.name,
        "logo_url": company.logo_url,
        "period": period_label,
        "generated_at": format_datetime_tr(datetime.now(timezone.utc)),
        "ai_summary": ai_summary,
        "ai_actions": ai_actions,
        "rows": rows,
        "section_titles": list(SECTION_TITLES),
        "total_contract": format_currency_tr(portfolio["contract"]),
        "total_invoiced": format_currency_tr(portfolio["invoiced"]),
        "total_collected": format_currency_tr(portfolio["collected"]),
        "total_outstanding": format_currency_tr(portfolio["outstanding"]),
        "collected_pct": format_pct_tr(
            float(portfolio["collected"] / portfolio["invoiced"] * 100) if portfolio["invoiced"] > 0 else 0
        ),
        # CR-006-A section datasets.
        "cover_kpis": cover_kpis,
        "margin_movement": margin_movement,
        "collection_rows": collection_rows,
        "budget_summary": budget_summary,
        "budget_total": budget_total,
        "overdue_payments": overdue_payments,
        "subcontractor_commitments": subcontractor_commitments,
        "action_items": action_items,
        # CR-005-A chart datasets (numeric, render-agnostic).
        "margin_chart": margin_chart,
        "budget_chart": budget_chart,
        "cashflow_chart": cashflow_chart,
    }


# CR-006-A: cover-page risk label per portfolio RAG.
_RISK_LABELS = {"green": "Düşük", "amber": "Orta", "red": "Yüksek"}
_RAG_ORDER = {"green": 0, "amber": 1, "red": 2}


def _worse_rag(a: str, b: str) -> str:
    return a if _RAG_ORDER.get(a, 0) >= _RAG_ORDER.get(b, 0) else b


def _margin_rag(pct: float) -> str:
    """§3/§2 margin colour: < %5 kırmızı, %5–%10 amber, > %10 yeşil."""
    if pct < 5:
        return "red"
    if pct <= 10:
        return "amber"
    return "green"


def _active_projects(db: Session, company: Company):
    from sqlalchemy import select

    return db.execute(
        select(Project).where(
            Project.company_id == company.id,
            Project.is_deleted.is_(False),
            Project.status == "active",
        )
    ).scalars().all()


def _company_overdue_payments(db: Session, company: Company, today) -> list[dict]:
    """§6/§7: unpaid cost entries whose payment_due_date is in the past."""
    from sqlalchemy import select

    from app.models.cost_entry import CostEntry

    project_names = {
        p.id: p.name for p in _active_projects(db, company)
    }
    rows = db.execute(
        select(CostEntry).where(
            CostEntry.company_id == company.id,
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),
            CostEntry.entry_type != "forecast",
            CostEntry.payment_status != "paid",
            CostEntry.payment_due_date.is_not(None),
            CostEntry.payment_due_date < today,
        )
    ).scalars().all()
    out = []
    for c in rows:
        remaining = D(c.total_with_vat_try) - D(c.amount_paid_try)
        if remaining <= 0:
            continue
        days = (today - c.payment_due_date).days
        out.append({
            "supplier": c.supplier_name or "Bilinmeyen Tedarikçi",
            "project": project_names.get(c.project_id, ""),
            "amount": format_currency_tr(remaining),
            "amount_d": remaining,
            "due_date": format_date_tr(c.payment_due_date),
            "days": days,
            "severe": days >= 30,
        })
    out.sort(key=lambda r: r["days"], reverse=True)
    return out


def _subcontractor_commitments(db: Session, company: Company) -> list[dict]:
    """§6: top 5 active subcontractor commitments by revised contract value."""
    from sqlalchemy import select

    from app.calculations.subcontractor import subcontractor_revised_contract
    from app.models.cost_entry import CostEntry
    from app.models.subcontractor import Subcontractor

    subs = db.execute(
        select(Subcontractor).where(
            Subcontractor.company_id == company.id,
            Subcontractor.is_deleted.is_(False),
            Subcontractor.status == "active",
        )
    ).scalars().all()
    if not subs:
        return []
    # Paid-to-date per subcontractor (linked cost entries).
    paid_by_sub: dict = {}
    for c in db.execute(
        select(CostEntry).where(
            CostEntry.company_id == company.id,
            CostEntry.is_deleted.is_(False),
            CostEntry.subcontractor_id.is_not(None),
        )
    ).scalars().all():
        paid_by_sub[c.subcontractor_id] = D(paid_by_sub.get(c.subcontractor_id, D(0))) + D(c.amount_paid_try)

    items = []
    for s in subs:
        revised = subcontractor_revised_contract(s.contract_value_try, s.approved_variations_try)
        paid = D(paid_by_sub.get(s.id, D(0)))
        remaining = revised - paid
        pct_done = float(paid / revised * 100) if revised > 0 else 0.0
        items.append({
            "name": s.name,
            "scope": s.scope_of_work or "—",
            "contract": format_currency_tr(revised),
            "paid": format_currency_tr(paid),
            "remaining": format_currency_tr(remaining),
            "pct_done": format_pct_tr(pct_done),
            "revised_d": revised,
        })
    items.sort(key=lambda x: D(x["revised_d"]), reverse=True)
    return items[:5]


def _build_action_items(rows, margin_movement, overdue_payments, budget_summary,
                        ai_actions, period_label) -> list[str]:
    """§7: build a prioritised, project-specific action list from real data.

    Rules (in priority order): overdue payments, budget overruns, large
    outstanding receivables, low margin, then up to 2 AI-derived actions. Generic
    advice is never added — when no concrete rule fires we emit the explicit
    "no urgent risk" line.
    """
    items: list[str] = []

    # Rule 1 — overdue payments.
    for o in overdue_payments[:3]:
        items.append(f"ACİL: {o['supplier']}'a {o['amount']} vadesi geçmiş ödeme — {o['days']} gün gecikti.")

    # Rule 2 — budget overruns (> %100 spent).
    for b in budget_summary:
        if b["pct_value"] > 100:
            items.append(
                f"{b['label']} kategorisi bütçeyi {format_pct_tr(b['pct_value'] - 100)} aştı — "
                f"Revize Bütçe: {b['revised']}."
            )

    # Rule 3 — outstanding receivable > %15 of contract.
    for r in rows:
        if r["outstanding_high"]:
            items.append(
                f"{r['name']}: {r['outstanding']} tahsilat bekliyor — müşteri ile acil görüşme yapın."
            )

    # Rule 4 — forecast margin < %10.
    for r in rows:
        if r["margin_value"] < 10:
            items.append(
                f"{r['name']}: Kar marjı {r['margin']} seviyesine düştü — maliyet kontrolü gerekli."
            )

    concrete = len(items)

    # Rule 5 — up to 2 AI-derived actions, but only as a supplement to real findings.
    if concrete:
        for line in _strip_action_lines(ai_actions)[:2]:
            items.append(line)

    items = items[:10]
    if not concrete:
        return ["Bu dönemde acil eylem gerektiren finansal risk tespit edilmemiştir."]
    return items


def _strip_action_lines(text) -> list[str]:
    """Turn an AI action blob into clean plain-text lines (no markdown/numbering)."""
    import re

    lines = []
    for raw in str(text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        s = re.sub(r"^\s*(\d+[\.\)]|[-*•])\s*", "", s)   # leading numbering / bullets
        s = s.replace("**", "").replace("##", "").replace("`", "").strip()
        if s:
            lines.append(s)
    return lines


def _parse_period_anchor(period_label: str):
    """Best-effort anchor date from a period string ("2026-06" -> 2026-06-15).

    Falls back to today when the label is free-form ("Bu Ay", "Haziran 2026").
    """
    from datetime import date

    try:
        parts = str(period_label).split("-")
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 15)
    except (ValueError, TypeError):
        pass
    return date.today()


def render_management_pack(db: Session, company: Company, period_label: str) -> bytes:
    return _management_pack_pdf(build_management_pack_data(db, company, period_label))


# ---------------------------------------------------------------------------
# ReportLab rendering helpers (imported lazily; stubbed in tests)
# ---------------------------------------------------------------------------
def _styles():
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    register_turkish_fonts()
    base = getSampleStyleSheet()
    s = {
        "company": ParagraphStyle(
            "company", parent=base["Normal"], fontName=FONT_BOLD,
            fontSize=15, textColor=PRIMARY,
        ),
        "title": ParagraphStyle(
            "title", parent=base["Normal"], fontName=FONT_BOLD,
            fontSize=17, textColor=PRIMARY, alignment=TA_RIGHT,
        ),
        "meta": ParagraphStyle(
            "meta", parent=base["Normal"], fontName=FONT_NORMAL, fontSize=9, textColor=MUTED, alignment=TA_RIGHT,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Normal"], fontName=FONT_BOLD,
            fontSize=14, textColor=PRIMARY, spaceBefore=14, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3", parent=base["Normal"], fontName=FONT_BOLD,
            fontSize=11, textColor=PRIMARY, spaceBefore=8, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName=FONT_NORMAL,
            fontSize=9, textColor="#1E293B", leading=14,
        ),
        "note": ParagraphStyle(
            "note", parent=base["Normal"], fontName=FONT_OBLIQUE,
            fontSize=8, textColor=MUTED, leading=12, spaceBefore=4, spaceAfter=4,
        ),
        # CR-006-A cover-page styles.
        "band_brand": ParagraphStyle(
            "band_brand", parent=base["Normal"], fontName=FONT_BOLD, fontSize=22, textColor="#FFFFFF",
        ),
        "band_title": ParagraphStyle(
            "band_title", parent=base["Normal"], fontName=FONT_BOLD, fontSize=16, textColor="#FFFFFF",
            alignment=TA_RIGHT,
        ),
        "cover_period": ParagraphStyle(
            "cover_period", parent=base["Normal"], fontName=FONT_BOLD, fontSize=28, textColor=NAVY,
        ),
        "cover_company": ParagraphStyle(
            "cover_company", parent=base["Normal"], fontName=FONT_NORMAL, fontSize=18, textColor=PRIMARY,
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta", parent=base["Normal"], fontName=FONT_NORMAL, fontSize=10, textColor=MUTED,
        ),
        "cover_kpi_label": ParagraphStyle(
            "cover_kpi_label", parent=base["Normal"], fontName=FONT_NORMAL, fontSize=8, textColor=MUTED,
        ),
        "cover_kpi_value": ParagraphStyle(
            "cover_kpi_value", parent=base["Normal"], fontName=FONT_BOLD, fontSize=12, textColor=PRIMARY,
        ),
        "ai": ParagraphStyle(
            "ai", parent=base["Normal"], fontName=FONT_NORMAL, fontSize=10, textColor="#1E293B",
            leading=15, backColor="#EFF6FF", borderColor=PRIMARY, borderWidth=0,
            leftIndent=8, rightIndent=8, spaceBefore=4, spaceAfter=4,
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer", parent=base["Normal"], fontName=FONT_OBLIQUE,
            fontSize=8, textColor="#94A3B8", alignment=TA_LEFT, spaceBefore=8,
        ),
        "kpi_label": ParagraphStyle(
            "kpi_label", parent=base["Normal"], fontName=FONT_NORMAL, fontSize=8, textColor=MUTED,
        ),
        "kpi_value": ParagraphStyle(
            "kpi_value", parent=base["Normal"], fontName=FONT_BOLD, fontSize=13, textColor=PRIMARY,
        ),
    }
    return s


def _logo_flowable(logo_url, max_h=44.0, max_w=120.0):
    """Return a ReportLab Image for the logo, or None if it cannot be loaded.

    CR-006-D: remote (http/https) logos are downloaded into memory with a short
    timeout so the company logo embeds in the PDF. Any failure (no URL, network
    error, bad image) falls back silently to the 'YAPI' text — the logo is
    optional and must never break the whole report.
    """
    if not logo_url:
        return None
    try:
        import io

        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image

        source = logo_url
        if isinstance(logo_url, str) and logo_url.lower().startswith(("http://", "https://")):
            import httpx

            resp = httpx.get(logo_url, timeout=5)
            resp.raise_for_status()
            source = io.BytesIO(resp.content)

        reader = ImageReader(source)
        iw, ih = reader.getSize()
        # Scale to fit within max_w x max_h, preserving aspect ratio.
        ratio = (iw / ih) if ih else 1.0
        h = max_h
        w = h * ratio
        if w > max_w:
            w = max_w
            h = w / ratio if ratio else max_h
        if isinstance(source, io.BytesIO):
            source.seek(0)
        return Image(source, width=w, height=h)
    except Exception:
        # Logo is optional — never fail the whole report over it.
        return None


def _header_table(styles, logo_url, company_name, title, subtitle):
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Table, TableStyle

    logo = _logo_flowable(logo_url)
    left = [logo] if logo else []
    left.append(Paragraph(company_name, styles["company"]))
    right = [Paragraph(title, styles["title"]), Paragraph(subtitle, styles["meta"])]
    t = Table([[left, right]], colWidths=[10 * cm, 7.5 * cm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 2, colors.HexColor(PRIMARY)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _data_table(rows, col_widths, num_cols=(), header=True, rag_col=None, rag_values=None,
                bg_cells=None, row_bg=None):
    """Build a styled Platypus table. ``rows`` includes the header row when header=True.

    ``bg_cells`` colour-codes individual cells: a list of (col, data_row_idx, rag).
    ``row_bg`` colour-codes whole data rows: a list of (data_row_idx, rag). Both use
    the light RAG_TINTS palette so text stays readable. Padding is 6pt (CR-006-A).
    """
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT_NORMAL),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1 if header else 0), (-1, -1), colors.HexColor("#1E293B")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(PRIMARY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
        ]
    for c in num_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    off = 1 if header else 0
    if row_bg:
        for i, rag in row_bg:
            r = i + off
            style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor(RAG_TINTS.get(rag, "#FFFFFF"))))
    if bg_cells:
        for col, i, rag in bg_cells:
            r = i + off
            style.append(("BACKGROUND", (col, r), (col, r), colors.HexColor(RAG_TINTS.get(rag, "#FFFFFF"))))
            style.append(("FONTNAME", (col, r), (col, r), FONT_BOLD))
    if rag_col is not None and rag_values:
        for i, rag in enumerate(rag_values):
            r = i + off
            style.append(("TEXTCOLOR", (rag_col, r), (rag_col, r), colors.HexColor(RAG_COLORS.get(rag, MUTED))))
            style.append(("FONTNAME", (rag_col, r), (rag_col, r), FONT_BOLD))
    t.setStyle(TableStyle(style))
    return t


def _footer_painter(generated_at, note=None):
    """Return an onPage callback drawing page numbers + generated-by (+ optional note)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4

    def paint(canvas, doc):
        register_turkish_fonts()
        canvas.saveState()
        width, _ = A4
        canvas.setFont(FONT_NORMAL, 8)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawCentredString(width / 2, 1.0 * 28.35, f"Sayfa {doc.page}")
        canvas.setFont(FONT_NORMAL, 7)
        canvas.setFillColor(colors.HexColor("#94A3B8"))
        canvas.drawString(1.4 * 28.35, 1.0 * 28.35, f"Yapı tarafından {generated_at} tarihinde oluşturuldu")
        if note:
            canvas.setFont(FONT_OBLIQUE, 6)
            canvas.drawString(1.4 * 28.35, 0.6 * 28.35, note)
        canvas.restoreState()

    return paint


def _render_story(story, generated_at, footer_note=None) -> bytes:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=1.6 * cm, bottomMargin=2 * cm, leftMargin=1.4 * cm, rightMargin=1.4 * cm,
        title="Yapı Rapor",
    )
    paint = _footer_painter(generated_at, footer_note)
    doc.build(story, onFirstPage=paint, onLaterPages=paint)
    return buf.getvalue()


def _project_report_pdf(d: dict) -> bytes:
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Spacer

    s = _styles()
    story = [
        _header_table(s, d["logo_url"], d["company_name"], d["report_title"], d["report_date"]),
        Spacer(1, 10),
        Paragraph(f"{d['project_name']} — {d['client_name']}", s["h2"]),
    ]

    # KPI strip as a 4-column table.
    def kpi(label, value):
        return [Paragraph(label, s["kpi_label"]), Paragraph(value, s["kpi_value"])]

    kpi_row = [
        kpi("Sözleşme Değeri", d["contract_value"]),
        kpi("Gerçekleşen Maliyet", d["total_actual"]),
        kpi("Final Tahmin", d["forecast_final"]),
        kpi("Kar Marjı", d["margin_pct"]),
    ]
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    kt = Table([kpi_row], colWidths=[4.375 * cm] * 4)
    kt.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [kt, Spacer(1, 6)]

    # Budget vs actual by category.
    story.append(Paragraph("Bütçe & Gerçekleşen (Kategori Bazında)", s["h2"]))
    rows = [["Kategori", "Revize Bütçe", "Faturalanan", "Final Tahmin", "Sapma", "Durum"]]
    rags = []
    for c in d["categories"]:
        rows.append([c["label"], c["revised"], c["invoiced"], c["forecast"], c["variance"], c["status_label"]])
        rags.append(c["status"])
    story.append(_data_table(
        rows, col_widths=[5 * cm, 2.7 * cm, 2.7 * cm, 2.7 * cm, 2.4 * cm, 2.1 * cm],
        num_cols=(1, 2, 3, 4), rag_col=5, rag_values=rags,
    ))

    # Income & collection summary.
    story.append(Paragraph("Gelir & Tahsilat Özeti", s["h2"]))
    summary = [
        ["İşverene Faturalanan", d["total_invoiced"]],
        ["Tahsil Edilen", d["total_collected"]],
        ["Bekleyen Tahsilat", d["total_outstanding"]],
        ["Hakediş Kesintisi", d["total_retention"]],
        ["Net Nakit Pozisyonu", d["net_cash"]],
    ]
    story.append(_data_table(summary, col_widths=[12 * cm, 5.6 * cm], num_cols=(1,), header=False))

    return _render_story(story, d["generated_at"])


_TR_MONTHS_SHORT = [
    "", "Oca", "Şub", "Mar", "Nis", "May", "Haz",
    "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara",
]


def _month_label_tr(month_key: str) -> str:
    """'2026-06' -> 'Haz 26' for compact chart axis labels."""
    try:
        y, m = month_key.split("-")
        return f"{_TR_MONTHS_SHORT[int(m)]} {y[2:]}"
    except (ValueError, IndexError):
        return month_key


def _bar_color_for_margin(pct):
    """CR-005-A Grafik 1: < %10 kırmızı, %10–%20 amber, > %20 yeşil."""
    if pct < 10:
        return RAG_COLORS["red"]
    if pct <= 20:
        return RAG_COLORS["amber"]
    return RAG_COLORS["green"]


def _bar_color_for_usage(pct):
    """CR-005-A Grafik 2: %85 üzeri amber, %100 üzeri kırmızı, altı mavi."""
    if pct > 100:
        return RAG_COLORS["red"]
    if pct >= 85:
        return RAG_COLORS["amber"]
    return "#3B82F6"


def _grouped_bar_chart(title, categories, series, colors_per_series=None, color_fn=None,
                       value_suffix="", width=400, height=200, value_min=0):
    """Build a Platypus-embeddable grouped vertical bar chart Drawing.

    ``series`` is a list of (label, [values]) tuples. When ``color_fn`` is given it
    colours each bar of the first series by value (single-series charts); otherwise
    ``colors_per_series`` colours each whole series. Returns a list of flowables
    (title + drawing) so callers can splice it straight into the story.
    """
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.legends import Legend
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors as rl_colors
    from reportlab.platypus import Paragraph

    register_turkish_fonts()
    s = _styles()
    flowables = [Paragraph(title, s["h2"])]

    if not categories or not series or not any(vals for _, vals in series):
        # Empty-state — never render a blank axis box.
        flowables.append(Paragraph("Veri yok — bu dönem için grafik oluşturulamadı.", s["body"]))
        return flowables

    drawing = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x = 35
    chart.y = 30
    chart.width = width - 60
    chart.height = height - 55
    chart.data = [vals for _, vals in series]
    chart.categoryAxis.categoryNames = categories
    chart.categoryAxis.labels.fontName = FONT_NORMAL
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.angle = 20
    chart.categoryAxis.labels.dy = -4
    chart.valueAxis.labels.fontName = FONT_NORMAL
    chart.valueAxis.labels.fontSize = 7
    if value_min is not None:
        chart.valueAxis.valueMin = value_min
    chart.barLabels.fontName = FONT_NORMAL
    chart.barLabels.fontSize = 6
    chart.barLabelFormat = (lambda v: f"{format_pct_tr(v)}") if value_suffix == "%" else None
    chart.barLabels.nudge = 6

    if color_fn is not None:
        # Single series, per-bar colouring.
        vals = series[0][1]
        for i, v in enumerate(vals):
            chart.bars[(0, i)].fillColor = rl_colors.HexColor(color_fn(v))
    else:
        palette = colors_per_series or ["#1B2B4B", "#3B82F6", ACCENT]
        for si in range(len(series)):
            chart.bars[si].fillColor = rl_colors.HexColor(palette[si % len(palette)])

    drawing.add(chart)

    # Legend for multi-series charts.
    if color_fn is None and len(series) > 1:
        legend = Legend()
        legend.x = 35
        legend.y = height - 8
        legend.dx = 8
        legend.dy = 8
        legend.fontName = FONT_NORMAL
        legend.fontSize = 7
        legend.alignment = "right"
        legend.columnMaximum = 1
        legend.deltax = 90
        palette = colors_per_series or ["#1B2B4B", "#3B82F6", ACCENT]
        legend.colorNamePairs = [
            (rl_colors.HexColor(palette[i % len(palette)]), lbl) for i, (lbl, _) in enumerate(series)
        ]
        drawing.add(legend)

    flowables.append(drawing)
    return flowables


def _cover_page(s, d) -> list:
    """CR-006-A: professional cover page — navy band, period, company, KPI strip."""
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    kpis = d.get("cover_kpis") or {}
    logo = _logo_flowable(d.get("logo_url"))
    brand = logo if logo else Paragraph("YAPI", s["band_brand"])
    # Top navy band: brand left, document title right.
    band = Table(
        [[brand, Paragraph("AYLIK YÖNETİM PAKETİ", s["band_title"])]],
        colWidths=[8.5 * cm, 9 * cm], rowHeights=[1.9 * cm],
    )
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(NAVY)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 14),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 14),
    ]))

    # KPI strip — 4 boxes with coloured top borders.
    def kpi_box(label, value, color):
        inner = Table([[Paragraph(label, s["cover_kpi_label"])],
                       [Paragraph(value, s["cover_kpi_value"])]], colWidths=[4.1 * cm])
        inner.setStyle(TableStyle([
            ("LINEABOVE", (0, 0), (-1, 0), 3, colors.HexColor(color)),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDER)),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return inner

    strip = Table([[
        kpi_box("Aktif Projeler", kpis.get("active_projects", "0"), "#3B82F6"),
        kpi_box("Toplam Sözleşme", kpis.get("total_contract", ""), NAVY),
        kpi_box("Bekleyen Tahsilat", kpis.get("total_outstanding", ""), ACCENT),
        kpi_box("Bu Ay Risk", kpis.get("risk_level", ""), RAG_COLORS.get(kpis.get("risk_rag", "green"), "#10B981")),
    ]], colWidths=[4.375 * cm] * 4)
    strip.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))

    return [
        band,
        Spacer(1, 64),
        Paragraph(d["period"], s["cover_period"]),
        Spacer(1, 6),
        Paragraph(d["company_name"], s["cover_company"]),
        Spacer(1, 4),
        Paragraph(f"Yapı tarafından {d['generated_at']} tarihinde oluşturuldu", s["cover_meta"]),
        Spacer(1, 56),
        strip,
        Spacer(1, 40),
        Paragraph(AI_DISCLAIMER, s["disclaimer"]),
    ]


def _format_ai_md(text) -> str:
    """Render lightweight Markdown (**bold**, ## başlık) as formatted Paragraph XML."""
    import re
    from xml.sax.saxutils import escape

    out_lines = []
    for raw in str(text or "").splitlines():
        line = escape(raw)
        header = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if header:
            out_lines.append(f"<b>{header.group(1).strip()}</b>")
            continue
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        out_lines.append(line)
    return "<br/>".join(out_lines)


def _management_pack_pdf(d: dict) -> bytes:
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, PageBreak, Spacer

    s = _styles()
    titles = d.get("section_titles") or SECTION_TITLES
    header = _header_table(s, d["logo_url"], d["company_name"], "Aylık Yönetim Paketi", d["period"])

    # Page 1 — cover page (CR-006-A).
    story = _cover_page(s, d)
    story.append(PageBreak())

    # Page 2 — executive summary (AI), formatted in three colour-coded blocks.
    story += [header, Spacer(1, 8), Paragraph(titles[0], s["h2"]),
              Paragraph(_format_ai_md(d["ai_summary"]), s["ai"]),
              Paragraph(AI_DISCLAIMER, s["disclaimer"]), PageBreak()]

    # Page 3 — project financial KPIs with colour-coded margin cells.
    story.append(Paragraph(titles[1], s["h2"]))
    rows = [["Proje", "İşveren", "Sözleşme", "Gerçekleşen", "% İlerleme",
             "Hedef Marj", "Marj", "Bekleyen", "Durum"]]
    rags = []
    margin_cells = []
    outstanding_cells = []
    for i, r in enumerate(d["rows"]):
        rows.append([r["name"], r["client"], r["contract"], r["actual"], r["completion"],
                     r["target_margin"], r["margin"], r["outstanding"], "●"])
        rags.append(r["rag"])
        margin_cells.append((6, i, _margin_rag(r["margin_value"])))
        if r["outstanding_high"]:
            outstanding_cells.append((7, i, "amber"))
    story.append(_data_table(
        rows,
        col_widths=[2.9 * cm, 2.1 * cm, 2.3 * cm, 2.3 * cm, 1.7 * cm, 1.7 * cm, 1.6 * cm, 2.3 * cm, 1.0 * cm],
        num_cols=(2, 3, 4, 5, 6, 7), rag_col=8, rag_values=rags,
        bg_cells=margin_cells + outstanding_cells,
    ))
    # Row-below totals.
    story.append(Spacer(1, 4))
    story.append(_data_table(
        [["TOPLAM", d["total_contract"], d["total_collected"], d["total_outstanding"]]],
        col_widths=[6 * cm, 4 * cm, 4 * cm, 3.6 * cm], num_cols=(1, 2, 3), header=False,
        row_bg=[(0, "gray")],
    ))
    # CR-005-A Grafik 1 — Proje bazında hedef vs gerçekleşen kar marjı.
    mc = d.get("margin_chart") or []
    story.append(Spacer(1, 10))
    story += _grouped_bar_chart(
        "Proje Bazında Kar Marjı — Hedef vs Gerçekleşen (%)",
        [_short(m["name"]) for m in mc],
        [
            ("Hedef Marj", [m["target_pct"] for m in mc]),
            ("Gerçekleşen Marj", [m["forecast_pct"] for m in mc]),
        ],
        colors_per_series=["#9CA3AF", "#3B82F6"],
        value_suffix="%", value_min=None, width=500, height=220,
    )
    story.append(PageBreak())

    # Page 4 — margin movement (real per-project category tables).
    story.append(Paragraph(titles[2], s["h2"]))
    mm = d.get("margin_movement") or []
    if not mm:
        story.append(Paragraph("Bu dönemde aktif proje bulunmamaktadır.", s["body"]))
    for proj in mm:
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            f"{proj['name']} — Tahmini Final Marj: <b>{proj['final_margin']}</b>", s["h3"]))
        if proj["categories"]:
            crows = [["Kategori", "Orijinal Bütçe", "Revize Bütçe", "Faturalanan", "Sapma", "% Harcanan"]]
            cell_bg = []
            for i, c in enumerate(proj["categories"]):
                crows.append([c["label"], c["original"], c["revised"], c["invoiced"], c["variance"], c["pct_spent"]])
                cell_bg.append((4, i, c["status"]))
            story.append(_data_table(
                crows, col_widths=[4.2 * cm, 2.9 * cm, 2.9 * cm, 2.9 * cm, 2.4 * cm, 2.1 * cm],
                num_cols=(1, 2, 3, 4, 5), bg_cells=cell_bg,
            ))
        else:
            story.append(Paragraph("Bu proje için kategori hareketi bulunmamaktadır.", s["body"]))
        story.append(Paragraph(proj["driver_text"], s["note"]))
    story.append(PageBreak())

    # Page 5 — cash flow & collection.
    story.append(Paragraph(titles[3], s["h2"]))
    cash = [
        ["Toplam Sözleşme Değeri", d["total_contract"]],
        [f"Toplam Tahsil Edilen ({d.get('collected_pct', '')})", d["total_collected"]],
        ["Toplam Bekleyen Tahsilat", d["total_outstanding"]],
    ]
    story.append(_data_table(cash, col_widths=[12 * cm, 5.6 * cm], num_cols=(1,), header=False))
    # CR-005-A Grafik 3 — son 6 ay gelir vs gider.
    cf = d.get("cashflow_chart") or []
    story.append(Spacer(1, 10))
    story += _grouped_bar_chart(
        "Son 6 Ay Nakit Akışı — Gelir vs Gider (₺)",
        [_month_label_tr(m["month"]) for m in cf],
        [
            ("Gelir", [m["income"] for m in cf]),
            ("Gider", [m["expense"] for m in cf]),
        ],
        colors_per_series=[RAG_COLORS["green"], RAG_COLORS["red"]],
        width=500, height=200,
    )
    # Per-project collection / aging table.
    cr = d.get("collection_rows") or []
    if cr:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Proje Bazında Tahsilat", s["h3"]))
        crows = [["Proje", "Faturalanan", "Tahsil Edilen", "Bekleyen", "Gecikmiş Gün"]]
        row_bg = []
        for i, c in enumerate(cr):
            crows.append([c["name"], c["invoiced"], c["collected"], c["outstanding"], str(c["overdue_days"])])
            if c["overdue"]:
                row_bg.append((i, "red"))
        story.append(_data_table(
            crows, col_widths=[4.5 * cm, 3.3 * cm, 3.3 * cm, 3.3 * cm, 3 * cm],
            num_cols=(1, 2, 3, 4), row_bg=row_bg,
        ))
    story.append(PageBreak())

    # Page 6 — budget category detail (real aggregated table).
    story.append(Paragraph(titles[4], s["h2"]))
    # CR-005-A Grafik 2 — en pahalı 8 kategori için bütçe kullanımı (% harcanan).
    bc = d.get("budget_chart") or []
    story += _grouped_bar_chart(
        "Bütçe Kullanımı — En Yüksek 8 Kategori (% Harcanan)",
        [_short(b["label"]) for b in bc],
        [("% Harcanan", [b["spent_pct"] for b in bc])],
        color_fn=_bar_color_for_usage,
        value_suffix="%", width=500, height=200,
    )
    bs = d.get("budget_summary") or []
    story.append(Spacer(1, 10))
    if bs:
        brows = [["Kategori", "Revize Bütçe", "Taahhüt", "Faturalanan", "Kalan", "% Harcanan"]]
        row_bg = []
        for i, b in enumerate(bs):
            brows.append([b["label"], b["revised"], b["committed"], b["invoiced"], b["remaining"], b["pct_spent"]])
            if b["pct_value"] > 100:
                row_bg.append((i, "red"))
            elif b["pct_value"] >= 85:
                row_bg.append((i, "amber"))
        brows.append(["TOPLAM", d.get("budget_total", {}).get("revised", ""), "", "", "", ""])
        story.append(_data_table(
            brows, col_widths=[4.2 * cm, 2.9 * cm, 2.7 * cm, 2.9 * cm, 2.7 * cm, 2 * cm],
            num_cols=(1, 2, 3, 4, 5), row_bg=row_bg + [(len(bs), "gray")],
        ))
    else:
        story.append(Paragraph("Bu dönemde bütçe verisi girilmiş kategori bulunmamaktadır.", s["body"]))
    story.append(PageBreak())

    # Page 7 — subcontractor & supplier risk (real data).
    story.append(Paragraph(titles[5], s["h2"]))
    op = d.get("overdue_payments") or []
    sc = d.get("subcontractor_commitments") or []
    if op:
        story.append(Paragraph("Vadesi Geçmiş Ödemeler", s["h3"]))
        orows = [["Tedarikçi", "Proje", "Tutar", "Vade Tarihi", "Gecikme Günü"]]
        row_bg = []
        for i, o in enumerate(op):
            orows.append([o["supplier"], o["project"], o["amount"], o["due_date"], str(o["days"])])
            if o["severe"]:
                row_bg.append((i, "red"))
        story.append(_data_table(
            orows, col_widths=[4.2 * cm, 3.6 * cm, 3 * cm, 3 * cm, 2.6 * cm],
            num_cols=(2, 4), row_bg=row_bg,
        ))
        story.append(Spacer(1, 10))
    if sc:
        story.append(Paragraph("En Büyük 5 Alt Yüklenici Taahhüdü", s["h3"]))
        srows = [["Alt Yüklenici", "Kapsam", "Sözleşme", "Ödenen", "Kalan", "% Tamamlandı"]]
        for sub in sc:
            srows.append([sub["name"], _short(sub["scope"], 24), sub["contract"], sub["paid"],
                          sub["remaining"], sub["pct_done"]])
        story.append(_data_table(
            srows, col_widths=[3.4 * cm, 3.6 * cm, 2.8 * cm, 2.6 * cm, 2.6 * cm, 2.4 * cm],
            num_cols=(2, 3, 4, 5),
        ))
    if not op and not sc:
        story.append(Paragraph("Bu dönemde aktif alt yüklenici bulunmamaktadır.", s["body"]))
    story.append(PageBreak())

    # Page 8 — action list (dynamic, project-specific).
    story.append(Paragraph(titles[6], s["h2"]))
    items = d.get("action_items") or []
    if items and len(items) == 1 and items[0].startswith("Bu dönemde acil"):
        story.append(Paragraph(items[0], s["body"]))
    else:
        from xml.sax.saxutils import escape

        numbered = "<br/>".join(f"<b>{i}.</b> {escape(it)}" for i, it in enumerate(items, 1))
        story.append(Paragraph(numbered, s["ai"]))
    story.append(Paragraph(AI_DISCLAIMER, s["disclaimer"]))

    return _render_story(story, d["generated_at"], footer_note=AI_DISCLAIMER)


def _short(text, n=20) -> str:
    """Truncate a label to ``n`` chars for compact axis/cell display."""
    t = str(text or "")
    return t if len(t) <= n else t[: n - 1] + "…"


def _nl2br(text) -> str:
    """Escape text for Paragraph and turn newlines into <br/>."""
    from xml.sax.saxutils import escape

    return escape(str(text or "")).replace("\n", "<br/>")


# ---------------------------------------------------------------------------
# CR-011-C — Agent analysis export (PDF + Excel)
# An agent analysis = answer text + its chart(s) + citations. Self-contained
# (the caller passes the analysis the agent already produced; no re-run).
# ---------------------------------------------------------------------------
def build_agent_analysis_data(company: Company | None, analysis: dict) -> dict:
    """Shape the analysis for rendering (no ReportLab/openpyxl import — testable)."""
    now = datetime.now(timezone.utc)
    return {
        "company_name": company.name if company else "Yapı",
        "logo_url": company.logo_url if company else None,
        "title": analysis.get("title") or "Yapı AI Analizi",
        "question": analysis.get("question"),
        "answer_markdown": analysis.get("answer_markdown") or "",
        "charts": analysis.get("charts") or [],
        "citations": analysis.get("citations") or [],
        "generated_at": format_datetime_tr(now),
        "report_date": format_date_tr(now.date()),
    }


def render_agent_analysis_pdf(company: Company | None, analysis: dict) -> bytes:
    return _agent_analysis_pdf(build_agent_analysis_data(company, analysis))


def _agent_chart_flowables(s, ch: dict) -> list:
    """Render one agent chart as a titled data table (its underlying numbers) —
    honest and dialect/markup-safe for any chart_type (line/bar/composed)."""
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph

    out = [Paragraph(_nl2br(ch.get("title") or "Grafik"), s["h3"])]
    series = ch.get("series") or []
    data = ch.get("data") or []
    x_key = ch.get("x_key") or "x"
    if not series or not data:
        out.append(Paragraph("Grafik verisi yok.", s["body"]))
        return out
    header = [x_key] + [str(se.get("label") or se.get("key") or "") for se in series]
    rows = [header]
    for pt in data:
        row = [str(pt.get(x_key, ""))]
        for se in series:
            row.append(str(pt.get(se.get("key"), "")))
        rows.append(row)
    ncol = len(header)
    out.append(_data_table(
        rows, col_widths=[17.6 / ncol * cm] * ncol, num_cols=tuple(range(1, ncol)),
    ))
    if ch.get("source_note"):
        out.append(Paragraph(_nl2br(ch["source_note"]), s["note"]))
    return out


def _agent_analysis_pdf(d: dict) -> bytes:
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Spacer

    s = _styles()
    story = [
        _header_table(s, d["logo_url"], d["company_name"], d["title"], d["report_date"]),
        Spacer(1, 10),
    ]
    if d.get("question"):
        story.append(Paragraph(f"<b>Soru:</b> {_nl2br(d['question'])}", s["h3"]))
        story.append(Spacer(1, 4))

    story.append(Paragraph("Analiz", s["h2"]))
    story.append(Paragraph(_format_ai_md(d["answer_markdown"]), s["body"]))

    for ch in d["charts"]:
        story.append(Spacer(1, 8))
        story += _agent_chart_flowables(s, ch)

    cits = d["citations"]
    if cits:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Kaynaklar", s["h2"]))
        rows = [["Kaynak", "Bağlantı"]]
        for c in cits:
            rows.append([_short(str(c.get("label", "")), 60), str(c.get("deep_link", ""))])
        story.append(_data_table(rows, col_widths=[8.8 * cm, 8.8 * cm]))

    story.append(Spacer(1, 8))
    story.append(Paragraph(AI_DISCLAIMER, s["disclaimer"]))
    return _render_story(story, d["generated_at"], footer_note=AI_DISCLAIMER)


def _safe_sheet_title(title, idx: int) -> str:
    """Excel sheet titles: <=31 chars, none of []:*?/\\, unique (idx-prefixed)."""
    import re

    t = re.sub(r"[\[\]:\*\?/\\]", " ", str(title or "")).strip()
    return (f"{idx}-{t}" if t else f"Grafik {idx}")[:31]


def render_agent_analysis_excel(company: Company | None, analysis: dict) -> bytes:
    """Render the analysis to an .xlsx workbook: an Analiz sheet (answer text),
    one sheet per chart (its data), and a Kaynaklar sheet (citations)."""
    from io import BytesIO

    from openpyxl import Workbook

    d = build_agent_analysis_data(company, analysis)
    wb = Workbook()
    ws = wb.active
    ws.title = "Analiz"
    ws.append([d["title"]])
    ws.append(["Şirket", d["company_name"]])
    ws.append(["Oluşturulma", d["generated_at"]])
    if d.get("question"):
        ws.append(["Soru", d["question"]])
    ws.append([])
    ws.append(["Analiz"])
    answer_lines = _strip_action_lines(d["answer_markdown"]) or [d["answer_markdown"]]
    for line in answer_lines:
        ws.append([line])

    for idx, ch in enumerate(d["charts"], 1):
        cws = wb.create_sheet(title=_safe_sheet_title(ch.get("title"), idx))
        series = ch.get("series") or []
        x_key = ch.get("x_key") or "x"
        cws.append([x_key] + [str(se.get("label") or se.get("key") or "") for se in series])
        for pt in (ch.get("data") or []):
            cws.append([pt.get(x_key)] + [pt.get(se.get("key")) for se in series])

    cits = d["citations"]
    if cits:
        kws = wb.create_sheet(title="Kaynaklar")
        kws.append(["Kaynak", "Tür", "Bağlantı"])
        for c in cits:
            kws.append([c.get("label"), c.get("type"), c.get("deep_link")])

    info = wb.create_sheet(title="Bilgi")
    info.append([AI_DISCLAIMER])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
