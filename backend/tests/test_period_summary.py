"""Dashboard "Dönem Özeti" — GET /projects/{id}/period-summary?from_date&to_date.

Cost incurred by entry_date, invoiced by invoice_date, collected by date_received;
exact Decimal sums + USD snapshot sums for the same rows; from>to -> 422; isolation.
"""
from datetime import date
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry


def _login(client, seed, co="a"):
    client.login(seed[co]["users"][ROLE_DIRECTOR])
    return seed[co]["project"].id


def _cost(db, project, company, *, entry_date, twv, amount_usd=None):
    db.add(CostEntry(
        project_id=project.id, company_id=company.id, created_by=_dir_id(company),
        entry_date=entry_date, cost_category="other", entry_type="actual",
        amount_try=Decimal(twv), vat_rate=Decimal("0"), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal(twv), amount_usd=(Decimal(amount_usd) if amount_usd is not None else None),
        payment_status="unpaid",
    ))


def _invoice(db, project, company, *, number, invoice_date, amount, due_date,
             date_received=None, amount_received="0", amount_usd=None):
    db.add(ClientInvoice(
        project_id=project.id, company_id=company.id, created_by=_dir_id(company),
        invoice_number=number, invoice_date=invoice_date, due_date=due_date,
        amount_try=Decimal(amount), vat_rate=Decimal("0"), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal(amount), net_due_try=Decimal(amount),
        amount_received_try=Decimal(amount_received), date_received=date_received,
        amount_usd=(Decimal(amount_usd) if amount_usd is not None else None),
        payment_status=("paid" if date_received else "unpaid"),
    ))


_DIR_CACHE: dict = {}


def _dir_id(company):
    return _DIR_CACHE.get(company.id)


def _seed_period(db, seed, co="a"):
    company = seed[co]["company"]
    project = seed[co]["project"]
    _DIR_CACHE[company.id] = seed[co]["users"][ROLE_DIRECTOR].id
    # Costs: two in range (Mar+Apr 2025), one out of range (Jan).
    _cost(db, project, company, entry_date=date(2025, 3, 10), twv="100000", amount_usd="2500")
    _cost(db, project, company, entry_date=date(2025, 4, 5), twv="60000", amount_usd="1500")
    _cost(db, project, company, entry_date=date(2025, 1, 5), twv="999999", amount_usd="9999")  # out of range
    # Invoices: issued in range (Mar) collected in range (Apr); issued out of range (Jan).
    _invoice(db, project, company, number="INV-1", invoice_date=date(2025, 3, 15),
             amount="200000", due_date=date(2025, 4, 15), date_received=date(2025, 4, 20),
             amount_received="200000", amount_usd="5000")
    _invoice(db, project, company, number="INV-0", invoice_date=date(2025, 1, 1),
             amount="777777", due_date=date(2025, 2, 1), amount_usd="7777")  # out of range
    db.commit()


def _summary(client, pid, frm, to):
    return client.get(f"/api/v1/projects/{pid}/period-summary", params={"from_date": frm, "to_date": to})


# --------------------------------------------------------------------------- #
def test_period_totals_exact(client, seed, db):
    pid = _login(client, seed)
    _seed_period(db, seed)
    r = _summary(client, pid, "2025-03-01", "2025-04-30")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    # Cost incurred (Mar 100k + Apr 60k); Jan excluded.
    assert d["cost_incurred_try"] == "160000.00"
    # Invoiced by invoice_date in range: only INV-1 (Mar).
    assert d["invoiced_try"] == "200000.00"
    # Collected by date_received in range: INV-1 received Apr.
    assert d["collected_try"] == "200000.00"
    # net = collected - cost = 200000 - 160000 = 40000.
    assert d["net_try"] == "40000.00"
    assert d["cost_count"] == 2 and d["invoice_count"] == 1 and d["collected_count"] == 1


def test_period_usd_snapshot_sums(client, seed, db):
    pid = _login(client, seed)
    _seed_period(db, seed)
    d = _summary(client, pid, "2025-03-01", "2025-04-30").json()["data"]
    assert d["cost_incurred_usd"] == "4000.00"   # 2500 + 1500
    assert d["invoiced_usd"] == "5000.00"
    assert d["collected_usd"] == "5000.00"
    assert d["usd_missing_count"] == 0


def test_period_usd_missing_count(client, seed, db):
    pid = _login(client, seed)
    company, project = seed["a"]["company"], seed["a"]["project"]
    _DIR_CACHE[company.id] = seed["a"]["users"][ROLE_DIRECTOR].id
    _cost(db, project, company, entry_date=date(2025, 5, 1), twv="1000", amount_usd=None)  # no snapshot
    db.commit()
    d = _summary(client, pid, "2025-05-01", "2025-05-31").json()["data"]
    assert d["cost_incurred_try"] == "1000.00"
    assert d["cost_incurred_usd"] == "0.00"
    assert d["usd_missing_count"] == 1


def test_dates_outside_range_excluded(client, seed, db):
    pid = _login(client, seed)
    _seed_period(db, seed)
    # A window with no activity.
    d = _summary(client, pid, "2024-01-01", "2024-12-31").json()["data"]
    assert d["cost_incurred_try"] == "0.00"
    assert d["invoiced_try"] == "0.00"
    assert d["collected_try"] == "0.00"


def test_committed_and_forecast_excluded_from_period_cost(client, seed, db):
    # CR-023.1: "Maliyet (dönem)" is actual-only — a committed (or forecast) entry
    # in the window must NOT inflate it (it equals Gerçekleşen Maliyet).
    company, project = seed["a"]["company"], seed["a"]["project"]
    _DIR_CACHE[company.id] = seed["a"]["users"][ROLE_DIRECTOR].id
    pid = _login(client, seed)
    _cost(db, project, company, entry_date=date(2025, 3, 10), twv="100000")  # actual
    db.add(CostEntry(
        project_id=project.id, company_id=company.id, created_by=_dir_id(company),
        entry_date=date(2025, 3, 12), cost_category="other", entry_type="committed",
        amount_try=Decimal("120000"), vat_rate=Decimal("0"), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal("120000"), payment_status="unpaid",
    ))
    db.add(CostEntry(
        project_id=project.id, company_id=company.id, created_by=_dir_id(company),
        entry_date=date(2025, 3, 14), cost_category="other", entry_type="forecast",
        amount_try=Decimal("50000"), vat_rate=Decimal("0"), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal("50000"), payment_status="unpaid",
    ))
    db.commit()
    d = _summary(client, pid, "2025-03-01", "2025-03-31").json()["data"]
    assert d["cost_incurred_try"] == "100000.00"  # committed 120k + forecast 50k excluded
    assert d["cost_count"] == 1


def test_from_after_to_is_422(client, seed):
    pid = _login(client, seed)
    r = _summary(client, pid, "2025-06-01", "2025-03-01")
    assert r.status_code == 422
    assert "sonra olamaz" in r.json()["error"]["message"].lower()


def test_invalid_date_is_422(client, seed):
    pid = _login(client, seed)
    assert _summary(client, pid, "2025-13-99", "2025-12-31").status_code == 422


def test_company_isolation(client, seed, db):
    # Company B cannot read company A's project period summary.
    _login(client, seed, "a")
    a_pid = seed["a"]["project"].id
    _login(client, seed, "b")
    r = _summary(client, a_pid, "2025-01-01", "2025-12-31")
    assert r.status_code == 404
