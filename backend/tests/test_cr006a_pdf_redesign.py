"""CR-006-A / CR-036: professional management-pack PDF.

Every section carries real, project-specific data — cover-page KPIs, the margin
bridge from per-category variances, an aggregated commitment/budget breakdown,
subcontractor risk, and decision/action items derived dynamically (overdue
payments, overruns, low margin, assurance findings). No placeholders, no generic
AI advice. CR-036 rebuilt the pack into 11 sections; this file tracks the new
data-layer keys (margin_bridge / commitment_categories / decisions / action_plan).
"""
from datetime import date
from decimal import Decimal

import pytest

from app.constants import ROLE_DIRECTOR
from app.models.budget_line_item import BudgetLineItem
from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.services.reports import build_management_pack_data, render_management_pack


@pytest.fixture(autouse=True)
def _stub_ai(monkeypatch):
    """No network: stub the single AI call the data layer makes."""
    import app.services.ai as ai

    monkeypatch.setattr(ai, "management_summary", lambda ctx: "Yönetici özeti (test).")


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


# --- §3 margin bridge (replaces the old §3 margin movement) -----------------
def test_margin_bridge_has_real_category_data(db, seed):
    a = seed["a"]
    db.add(_budget(a, "material_concrete", "100000", "150000"))  # %50 overrun
    db.commit()

    data = build_management_pack_data(db, a["company"], "2026-06")
    bridge = data["margin_bridge"]
    labels = [r["kalem"] for r in bridge["rows"]]
    # The overran category is named in the bridge — derived from a REAL variance,
    # never a narrative string like "Hacim/karışım".
    assert any("Malzeme" in lbl for lbl in labels)
    assert all("Hacim" not in lbl for lbl in labels)
    assert bridge["opening_pct"] and bridge["closing_pct"]


def test_no_placeholder_text_in_report_source():
    """Sections must not fall back to 'başka sayfaya bakın'."""
    import app.services.reports as reports

    src = open(reports.__file__, encoding="utf-8").read()
    assert "başka sayfaya" not in src


# --- §4 commitment / budget breakdown (replaces the old §5 budget summary) --
def test_commitment_categories_aggregate_categories(db, seed):
    a = seed["a"]
    db.add(_budget(a, "materials", "100000", "120000"))
    db.add(_overdue_cost(a, "120000", "ABC Yapı"))
    db.commit()

    data = build_management_pack_data(db, a["company"], "2026-06")
    cats = data["commitment_categories"]
    assert any("Malzeme" in c["label"] or "materials" in c["label"].lower() for c in cats)
    mat = next(c for c in cats if "materials" in c["label"].lower() or "Malzeme" in c["label"])
    assert Decimal(mat["invoiced"]) == Decimal("120000")  # the 120k actual recorded


# --- §6 subcontractor risk --------------------------------------------------
def test_subcontractor_commitments_listed(db, seed):
    a = seed["a"]
    db.add(_subcontractor(a, "Demir Alt Yüklenici", "500000"))
    db.commit()

    data = build_management_pack_data(db, a["company"], "2026-06")
    sc = data["subcontractor_commitments"]
    assert len(sc) == 1
    assert sc[0]["name"] == "Demir Alt Yüklenici"
    assert "500.000,00 ₺" == sc[0]["contract"]


# --- §2 decisions / §11 action plan (replace the old action_items list) ------
def test_overdue_payment_surfaces_in_decisions(db, seed):
    a = seed["a"]
    db.add(_overdue_cost(a, "75000", "Gecikmiş Tedarikçi"))
    db.commit()

    data = build_management_pack_data(db, a["company"], "2026-06")
    match = [d for d in data["decisions"] if "Gecikmiş Tedarikçi" in d["konu"]]
    assert match
    assert match[0]["oncelik_rag"] == "r"  # >30 gün geciken → kritik
    assert match[0]["sahip"] == "Finans"


def test_action_plan_includes_overdue(db, seed):
    a = seed["a"]
    db.add(_overdue_cost(a, "75000", "Gecikmiş Tedarikçi"))
    db.commit()

    data = build_management_pack_data(db, a["company"], "2026-06")
    assert any("Gecikmiş Tedarikçi" in x["aksiyon"] for x in data["action_plan"])


def test_no_risk_empty_state(db, seed):
    """No costs/invoices/subs → a calm 'no decision' entry and EMPTY risk/action
    lists — never generic filler."""
    data = build_management_pack_data(db, seed["a"]["company"], "2026-06")
    assert data["decisions"][0]["oncelik_rag"] == "g"
    assert data["risk_register"] == []
    assert data["action_plan"] == []


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
    # CR-036: cover + 11 sections render across many pages (the old pack was 7).
    assert pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") > 7
    assert b"FontFile2" in pdf  # Türkçe TTF embedded
