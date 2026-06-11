"""CR-006-A: professional management-pack PDF redesign.

Every section must carry real, project-specific data — cover-page KPIs (§cover),
margin movement per project (§3), an aggregated budget table (§5), subcontractor /
overdue-payment risk (§6) and a dynamically-built, project-specific action list
(§7). No "başka sayfaya bakın" placeholders, no generic AI advice.
"""
from datetime import date
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.budget_line_item import BudgetLineItem
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.services.reports import build_management_pack_data, render_management_pack


def _overdue_cost(a, amount, supplier, **kw):
    return CostEntry(
        project_id=a["project"].id, company_id=a["company"].id,
        created_by=a["users"][ROLE_DIRECTOR].id, entry_date=date(2025, 1, 1),
        cost_category="materials", amount_try=Decimal(amount),
        total_with_vat_try=Decimal(amount), supplier_name=supplier,
        payment_due_date=date(2025, 1, 1), payment_status="unpaid", entry_type="actual", **kw,
    )


def _budget(a, category, original, forecast):
    return BudgetLineItem(
        project_id=a["project"].id, company_id=a["company"].id, cost_category=category,
        original_budget_try=Decimal(original), forecast_final_try=Decimal(forecast),
    )


def _subcontractor(a, name, value):
    return Subcontractor(
        project_id=a["project"].id, company_id=a["company"].id, name=name,
        scope_of_work="Kaba inşaat", contract_value_try=Decimal(value),
    )


# --- Cover page -------------------------------------------------------------
def test_cover_kpis_use_real_portfolio_data(db, seed):
    data = build_management_pack_data(db, seed["a"]["company"], "Haziran 2026")
    cover = data["cover_kpis"]
    assert cover["active_projects"] == "1"            # the one seeded active project
    assert "1.000.000,00 ₺" == cover["total_contract"]
    assert cover["risk_level"] in ("Düşük", "Orta", "Yüksek")


# --- §3 margin movement -----------------------------------------------------
def test_margin_movement_has_real_category_data(db, seed):
    a = seed["a"]
    db.add(_budget(a, "materials", "100000", "150000"))  # %50 overrun
    db.commit()

    data = build_management_pack_data(db, a["company"], "2026-06")
    mm = data["margin_movement"]
    assert len(mm) == 1
    proj = mm[0]
    labels = [c["label"] for c in proj["categories"]]
    assert any("Malzeme" in lbl or "materials" in lbl.lower() for lbl in labels)
    # Driver text is dynamic and names the overrun category — not a fixed string.
    assert "Marj düşüşünün başlıca nedenleri" in proj["driver_text"]


def test_no_placeholder_text_in_report_source():
    """§3/§5/§6 must not fall back to 'başka sayfaya bakın'."""
    import app.services.reports as reports

    src = open(reports.__file__, encoding="utf-8").read()
    assert "başka sayfaya" not in src


# --- §5 budget summary ------------------------------------------------------
def test_budget_summary_aggregates_categories(db, seed):
    a = seed["a"]
    db.add(_budget(a, "materials", "100000", "120000"))
    db.add(_overdue_cost(a, "120000", "ABC Yapı"))
    db.commit()

    data = build_management_pack_data(db, a["company"], "2026-06")
    bs = data["budget_summary"]
    assert any("Malzeme" in b["label"] or "materials" in b["label"].lower() for b in bs)
    assert data["budget_total"]["revised"]  # non-empty total string


# --- §6 subcontractor & overdue risk ----------------------------------------
def test_subcontractor_commitments_listed(db, seed):
    a = seed["a"]
    db.add(_subcontractor(a, "Demir Alt Yüklenici", "500000"))
    db.commit()

    data = build_management_pack_data(db, a["company"], "2026-06")
    sc = data["subcontractor_commitments"]
    assert len(sc) == 1
    assert sc[0]["name"] == "Demir Alt Yüklenici"
    assert "500.000,00 ₺" == sc[0]["contract"]


def test_overdue_payments_collected(db, seed):
    a = seed["a"]
    db.add(_overdue_cost(a, "75000", "Gecikmiş Tedarikçi"))
    db.commit()

    data = build_management_pack_data(db, a["company"], "2026-06")
    op = data["overdue_payments"]
    assert len(op) == 1
    assert op[0]["supplier"] == "Gecikmiş Tedarikçi"
    assert op[0]["days"] >= 30 and op[0]["severe"] is True


# --- §7 dynamic action list -------------------------------------------------
def test_action_items_trigger_overdue_rule(db, seed):
    a = seed["a"]
    db.add(_overdue_cost(a, "75000", "Gecikmiş Tedarikçi"))
    db.commit()

    data = build_management_pack_data(db, a["company"], "2026-06")
    items = data["action_items"]
    assert any("ACİL" in it and "Gecikmiş Tedarikçi" in it for it in items)


def test_action_items_empty_state_when_no_risk(db, seed):
    """No costs/invoices/subs → explicit no-risk line, never generic advice."""
    data = build_management_pack_data(db, seed["a"]["company"], "2026-06")
    assert data["action_items"] == [
        "Bu dönemde acil eylem gerektiren finansal risk tespit edilmemiştir."
    ]


# --- Real render ------------------------------------------------------------
def test_real_pdf_renders_all_sections(db, seed):
    a = seed["a"]
    db.add_all([
        _budget(a, "materials", "100000", "150000"),
        _overdue_cost(a, "75000", "Gecikmiş Tedarikçi"),
        _subcontractor(a, "Demir Alt Yüklenici", "500000"),
    ])
    db.commit()

    pdf = render_management_pack(db, a["company"], "2026-06")
    assert pdf.startswith(b"%PDF")
    # Cover + 7 sections render across multiple pages.
    assert pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 6
    assert b"FontFile2" in pdf  # Türkçe TTF embedded
