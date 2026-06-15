"""CR-007-A — read-only agent tool catalogue.

Exact-number correctness on the in-memory SQLite suite (§11.1): seed known data,
assert returned aggregates to the kuruş. Plus company-scoping / read-only checks
(§11.2). The pg_trgm fuzzy path is CR-007-D and is gated separately.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.services import agent_tools as T


def _cost(db, project, company_id, *, amount, vat=Decimal("0"), date_=date(2026, 1, 15),
          category="material_concrete", supplier="Akçansa", status="unpaid",
          entry_type="actual", paid=Decimal("0"), due=None, sub_id=None, created_by=None):
    c = CostEntry(
        project_id=project.id, company_id=company_id, entry_date=date_,
        cost_category=category, supplier_name=supplier,
        amount_try=Decimal(amount), vat_amount_try=Decimal(vat),
        total_with_vat_try=Decimal(amount) + Decimal(vat),
        payment_status=status, entry_type=entry_type, amount_paid_try=Decimal(paid),
        payment_due_date=due, subcontractor_id=sub_id, created_by=created_by,
    )
    db.add(c)
    db.flush()
    return c


def _invoice(db, project, company_id, *, number, amount, vat=Decimal("0"),
             date_=date(2026, 1, 10), due=date(2026, 2, 10), status="unpaid",
             received=Decimal("0"), inv_type="hakedis", created_by=None):
    net = Decimal(amount) + Decimal(vat)
    i = ClientInvoice(
        project_id=project.id, company_id=company_id, invoice_number=number,
        invoice_date=date_, invoice_type=inv_type, amount_try=Decimal(amount),
        vat_amount_try=Decimal(vat), total_with_vat_try=net, net_due_try=net,
        due_date=due, payment_status=status, amount_received_try=Decimal(received),
        created_by=created_by,
    )
    db.add(i)
    db.flush()
    return i


@pytest.fixture()
def cid(seed):
    return seed["a"]["company"].id


@pytest.fixture()
def director(seed):
    return seed["a"]["users"][ROLE_DIRECTOR]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def test_month_bucket_sqlite_emits_strftime(db):
    # On the SQLite test DB the helper must use strftime, not date_trunc.
    compiled = str(T.month_bucket(db, CostEntry.entry_date))
    assert "strftime" in compiled.lower()


def test_normalize_vendor_name_collapses_variants():
    assert T.normalize_vendor_name("Akçansa A.Ş.") == T.normalize_vendor_name("akçansa aş")
    assert T.normalize_vendor_name("  Beton   Ltd. Şti. ") == "BETON"


# --------------------------------------------------------------------------- #
# query_cost_entries — exact totals + grouping
# --------------------------------------------------------------------------- #
def test_query_cost_entries_exact_totals(db, seed, cid, director):
    p = seed["a"]["project"]
    _cost(db, p, cid, amount="1000.00", vat="200.00", created_by=director.id)
    _cost(db, p, cid, amount="2500.50", vat="500.10", created_by=director.id)

    out = T.query_cost_entries(db, cid)
    assert out["summary"]["total_amount_try"] == "3500.50"
    assert out["summary"]["total_with_vat_try"] == "4200.60"
    assert out["summary"]["entry_count"] == 2
    assert out["row_count"] == 2
    assert out["records"][0]["deep_link"].startswith(f"/projects/{p.id}/dashboard?highlight=")


def test_query_cost_entries_group_by_month_sqlite(db, seed, cid, director):
    p = seed["a"]["project"]
    _cost(db, p, cid, amount="1000", date_=date(2026, 1, 5), created_by=director.id)
    _cost(db, p, cid, amount="3000", date_=date(2026, 1, 20), created_by=director.id)
    _cost(db, p, cid, amount="500", date_=date(2026, 2, 2), created_by=director.id)

    groups = T.query_cost_entries(db, cid, group_by="month")["summary"]["groups"]
    by_key = {g["key"]: g for g in groups}
    assert by_key["2026-01"]["total_amount_try"] == "4000.00"
    assert by_key["2026-02"]["total_amount_try"] == "500.00"


def test_query_cost_entries_group_by_category(db, seed, cid, director):
    p = seed["a"]["project"]
    _cost(db, p, cid, amount="1000", category="material_steel", created_by=director.id)
    _cost(db, p, cid, amount="250", category="material_steel", created_by=director.id)
    _cost(db, p, cid, amount="800", category="labour_direct", created_by=director.id)

    groups = T.query_cost_entries(db, cid, group_by="category")["summary"]["groups"]
    by_key = {g["key"]: g["total_amount_try"] for g in groups}
    assert by_key["material_steel"] == "1250.00"
    assert by_key["labour_direct"] == "800.00"


def test_query_cost_entries_excludes_pending_approval(db, seed, cid, director):
    p = seed["a"]["project"]
    _cost(db, p, cid, amount="1000", created_by=director.id)
    pending = _cost(db, p, cid, amount="9999", created_by=director.id)
    pending.pending_approval = True
    db.flush()

    out = T.query_cost_entries(db, cid)
    assert out["summary"]["total_amount_try"] == "1000.00"
    assert out["summary"]["entry_count"] == 1


# --------------------------------------------------------------------------- #
# query_client_invoices
# --------------------------------------------------------------------------- #
def test_query_client_invoices_exact_totals(db, seed, cid, director):
    p = seed["a"]["project"]
    _invoice(db, p, cid, number="HAK-001", amount="10000", vat="2000", received="3000", created_by=director.id)
    _invoice(db, p, cid, number="HAK-002", amount="5000", vat="1000", received="0", created_by=director.id)

    out = T.query_client_invoices(db, cid)
    s = out["summary"]
    assert s["total_amount_try"] == "15000.00"
    assert s["total_net_due_try"] == "18000.00"   # (10000+2000)+(5000+1000)
    assert s["total_received_try"] == "3000.00"
    assert s["total_outstanding_try"] == "15000.00"
    assert s["invoice_count"] == 2


# --------------------------------------------------------------------------- #
# query_subcontractors — paid/remaining/retention
# --------------------------------------------------------------------------- #
def test_query_subcontractors_commitment_math(db, seed, cid, director):
    p = seed["a"]["project"]
    sub = Subcontractor(
        project_id=p.id, company_id=cid, name="Demir İnşaat",
        contract_value_try=Decimal("100000"), approved_variations_try=Decimal("20000"),
        retention_pct=Decimal("10.00"), status="active",
    )
    db.add(sub)
    db.flush()
    # 30,000 paid against this subcontractor across two cost entries.
    _cost(db, p, cid, amount="25000", paid="25000", status="paid", sub_id=sub.id, created_by=director.id)
    _cost(db, p, cid, amount="5000", paid="5000", status="paid", sub_id=sub.id, created_by=director.id)

    out = T.query_subcontractors(db, cid)
    rec = out["records"][0]
    assert rec["total_committed_try"] == "120000.00"
    assert rec["paid_to_date_try"] == "30000.00"
    assert rec["remaining_commitment_try"] == "90000.00"
    assert rec["retention_amount_try"] == "12000.00"
    assert out["summary"]["total_remaining_try"] == "90000.00"


# --------------------------------------------------------------------------- #
# get_overdue_payments — window math
# --------------------------------------------------------------------------- #
def test_get_overdue_payments_split(db, seed, cid, director):
    p = seed["a"]["project"]
    today = date(2026, 6, 15)
    # Overdue payable: due in the past, partially paid.
    _cost(db, p, cid, amount="10000", paid="4000", status="partial",
          due=date(2026, 5, 1), created_by=director.id)
    # Not overdue (future due) — must be excluded.
    _cost(db, p, cid, amount="8000", status="unpaid", due=date(2026, 7, 1), created_by=director.id)
    # Overdue receivable.
    _invoice(db, p, cid, number="HAK-OD", amount="20000", due=date(2026, 5, 10),
             status="unpaid", created_by=director.id)

    out = T.get_overdue_payments(db, cid, today=today)
    s = out["summary"]
    assert s["overdue_payable_total_try"] == "6000.00"   # 10000 - 4000
    assert s["overdue_payable_count"] == 1
    assert s["overdue_receivable_total_try"] == "20000.00"
    assert s["overdue_receivable_count"] == 1


# --------------------------------------------------------------------------- #
# list_projects + get_project_financials
# --------------------------------------------------------------------------- #
def test_list_projects_portfolio_summary(db, seed, cid):
    out = T.list_projects(db, cid)
    assert out["summary"]["project_count"] == 1
    assert out["summary"]["total_contract_value_try"] == "1000000.00"
    assert out["records"][0]["deep_link"] == f"/projects/{seed['a']['project'].id}/dashboard"


def test_get_project_financials_reuses_dashboard(db, seed, cid):
    p = seed["a"]["project"]
    out = T.get_project_financials(db, cid, p.id)
    assert out["summary"]["project_id"] == str(p.id)
    assert "forecast_at_completion" in out["summary"]
    assert "margin_pct" in out["summary"]


def test_get_project_financials_unknown_project_raises(db, seed, cid):
    import uuid as _uuid
    with pytest.raises(T.ToolError):
        T.get_project_financials(db, cid, _uuid.uuid4())


# --------------------------------------------------------------------------- #
# Company isolation (§11.2): company A's tools never see company B's data
# --------------------------------------------------------------------------- #
def test_company_isolation_cost_entries(db, seed, director):
    a_cid = seed["a"]["company"].id
    b_cid = seed["b"]["company"].id
    b_dir = seed["b"]["users"][ROLE_DIRECTOR]
    _cost(db, seed["a"]["project"], a_cid, amount="1000", created_by=director.id)
    _cost(db, seed["b"]["project"], b_cid, amount="7777", created_by=b_dir.id)

    a_out = T.query_cost_entries(db, a_cid)
    assert a_out["summary"]["total_amount_try"] == "1000.00"
    assert a_out["summary"]["entry_count"] == 1

    b_out = T.query_cost_entries(db, b_cid)
    assert b_out["summary"]["total_amount_try"] == "7777.00"


def test_project_scoped_tool_rejects_foreign_project(db, seed):
    """A company-A caller cannot pull company-B project financials."""
    a_cid = seed["a"]["company"].id
    b_project = seed["b"]["project"]
    with pytest.raises(T.ToolError):
        T.get_project_financials(db, a_cid, b_project.id)
