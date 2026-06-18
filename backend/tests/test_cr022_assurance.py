"""CR-022-D — Finans Güvence assurance rule pack + scan writer.

One test per rule (positive + clean), dedup on re-scan, dismissal respected,
company isolation, and the mandatory money-untouched guard (§3.4). SQLite-backed.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.calculations.money import D
from app.constants import ROLE_DIRECTOR
from app.models.ai_alert import AIAlert
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.services import assurance


# --- crafted-record helpers ------------------------------------------------ #
def _cost(db, seed, label="a", **over):
    p = seed[label]["project"]
    u = seed[label]["users"][ROLE_DIRECTOR]
    data = dict(
        project_id=p.id, company_id=p.company_id, entry_date=date(2025, 3, 1),
        cost_category="material", amount_try=D("1000"), vat_rate=D("20"),
        vat_amount_try=D("200"), total_with_vat_try=D("1200"), amount_usd=D("30"),
        vendor_id=uuid.uuid4(), created_by=u.id,
    )
    data.update(over)
    c = CostEntry(**data)
    db.add(c)
    db.flush()
    return c


def _inv(db, seed, label="a", **over):
    p = seed[label]["project"]
    u = seed[label]["users"][ROLE_DIRECTOR]
    data = dict(
        project_id=p.id, company_id=p.company_id, invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
        invoice_date=date(2025, 3, 1), amount_try=D("1000"), vat_rate=D("20"),
        vat_amount_try=D("200"), total_with_vat_try=D("1200"), net_due_try=D("1200"),
        due_date=date(2025, 4, 1), amount_usd=D("30"), created_by=u.id,
    )
    data.update(over)
    inv = ClientInvoice(**data)
    db.add(inv)
    db.flush()
    return inv


def _types(db, seed, label="a"):
    return assurance.collect_findings(db, seed[label]["company"].id)


def _of(findings, alert_type):
    return [f for f in findings if f["alert_type"] == alert_type]


# --- Rule 1: duplicates ---------------------------------------------------- #
def test_rule_duplicate_cost_flagged(db, seed):
    v = uuid.uuid4()
    _cost(db, seed, vendor_id=v, amount_try=D("1000"), entry_date=date(2025, 3, 1))
    _cost(db, seed, vendor_id=v, amount_try=D("1000"), entry_date=date(2025, 3, 2))
    db.commit()
    dup = _of(_types(db, seed), "duplicate_cost")
    assert len(dup) == 1
    assert dup[0]["severity"] == "high"
    assert "yinelen" in dup[0]["reasoning"].lower()
    assert dup[0]["source_type"] == "cost_entry"


def test_rule_duplicate_cost_clean_not_flagged(db, seed):
    v = uuid.uuid4()
    _cost(db, seed, vendor_id=v, amount_try=D("1000"), entry_date=date(2025, 3, 1))
    _cost(db, seed, vendor_id=v, amount_try=D("999"), entry_date=date(2025, 3, 1))  # diff amount
    db.commit()
    assert _of(_types(db, seed), "duplicate_cost") == []


def test_rule_duplicate_invoice_flagged(db, seed):
    _inv(db, seed, amount_try=D("5000"), invoice_date=date(2025, 3, 1))
    _inv(db, seed, amount_try=D("5000"), invoice_date=date(2025, 3, 2))
    db.commit()
    dup = _of(_types(db, seed), "duplicate_invoice")
    assert len(dup) == 1 and dup[0]["source_type"] == "client_invoice"


# --- Rule 2: cost outlier (with min-sample) -------------------------------- #
def test_rule_cost_outlier_flagged(db, seed):
    v = uuid.uuid4()
    for _ in range(5):
        _cost(db, seed, vendor_id=v, amount_try=D("1000"))
    big = _cost(db, seed, vendor_id=v, amount_try=D("10000"))  # > median(1000) × 3
    db.commit()
    out = _of(_types(db, seed), "cost_outlier")
    assert [f for f in out if f["source_id"] == big.id]
    assert out[0]["severity"] == "medium"
    assert "medyan" in out[0]["reasoning"].lower()


def test_rule_cost_outlier_min_sample_suppressed(db, seed):
    v = uuid.uuid4()
    for _ in range(3):  # only 3 comparable others (< 5) → suppress
        _cost(db, seed, vendor_id=v, amount_try=D("1000"))
    _cost(db, seed, vendor_id=v, amount_try=D("10000"))
    db.commit()
    assert _of(_types(db, seed), "cost_outlier") == []


# --- Rule 3: KDV mismatch + tolerance -------------------------------------- #
def test_rule_kdv_mismatch_flagged(db, seed):
    _cost(db, seed, amount_try=D("1000"), vat_rate=D("20"), vat_amount_try=D("500"), total_with_vat_try=D("1500"))
    db.commit()
    f = _of(_types(db, seed), "kdv_mismatch")
    assert len(f) == 1 and f[0]["severity"] == "high"


def test_rule_kdv_tolerance_not_flagged(db, seed):
    # vat off by 0.50 (≤ ±1 tolerance), total consistent → not flagged.
    _cost(db, seed, amount_try=D("1000.00"), vat_rate=D("20"), vat_amount_try=D("200.50"), total_with_vat_try=D("1200.50"))
    db.commit()
    assert _of(_types(db, seed), "kdv_mismatch") == []


def test_rule_kdv_invalid_rate_flagged(db, seed):
    # rate 19 is not in {0,1,10,20} nor tolerated {8,18}.
    _inv(db, seed, amount_try=D("1000"), vat_rate=D("19"), vat_amount_try=D("190"), total_with_vat_try=D("1190"), net_due_try=D("1190"))
    db.commit()
    assert _of(_types(db, seed), "kdv_mismatch")


# --- Rule 4: hakediş over contract ----------------------------------------- #
def test_rule_hakedis_over_contract_flagged(db, seed):
    # seed project contract_value_try = 1,000,000.
    _inv(db, seed, amount_try=D("700000"), invoice_date=date(2025, 3, 1))
    _inv(db, seed, amount_try=D("600000"), invoice_date=date(2025, 6, 1))
    db.commit()
    f = _of(_types(db, seed), "hakedis_over_contract")
    assert len(f) == 1 and f[0]["severity"] == "high"


def test_rule_hakedis_within_contract_not_flagged(db, seed):
    _inv(db, seed, amount_try=D("500000"))
    db.commit()
    assert _of(_types(db, seed), "hakedis_over_contract") == []


# --- Rule 5: missing FX ---------------------------------------------------- #
def test_rule_missing_fx_flagged(db, seed):
    _cost(db, seed, amount_usd=None)
    db.commit()
    f = _of(_types(db, seed), "missing_fx")
    assert len(f) == 1 and f[0]["severity"] == "low"


def test_rule_missing_fx_clean_not_flagged(db, seed):
    _cost(db, seed, amount_usd=D("30"))
    db.commit()
    assert _of(_types(db, seed), "missing_fx") == []


# --- Rule 6: unlinked vendor ----------------------------------------------- #
def test_rule_unlinked_vendor_flagged(db, seed):
    _cost(db, seed, vendor_id=None, subcontractor_id=None)
    db.commit()
    f = _of(_types(db, seed), "unlinked_vendor")
    assert len(f) == 1 and f[0]["severity"] == "low"


def test_rule_unlinked_vendor_clean_not_flagged(db, seed):
    _cost(db, seed, vendor_id=uuid.uuid4())
    db.commit()
    assert _of(_types(db, seed), "unlinked_vendor") == []


# --- Rule 7: non-positive amount ------------------------------------------- #
def test_rule_nonpositive_amount_flagged(db, seed):
    _inv(db, seed, amount_try=D("0"), vat_amount_try=D("0"), total_with_vat_try=D("0"),
         net_due_try=D("0"), amount_usd=D("0"))
    db.commit()
    f = _of(_types(db, seed), "nonpositive_amount")
    assert len(f) == 1 and f[0]["severity"] == "medium"


def test_clean_data_produces_no_findings(db, seed):
    # Fully consistent records (default helper values are arithmetically clean).
    _cost(db, seed, vendor_id=uuid.uuid4(), amount_usd=D("30"))
    _inv(db, seed)  # amount 1000 / vat 200 / total 1200 — consistent, within contract
    db.commit()
    assert assurance.collect_findings(db, seed["a"]["company"].id) == []


# --- Dedup / dismissal / isolation / money-untouched (scan_company) -------- #
def _dup_pair(db, seed, label="a"):
    v = uuid.uuid4()
    _cost(db, seed, label=label, vendor_id=v, amount_try=D("1000"), entry_date=date(2025, 3, 1))
    _cost(db, seed, label=label, vendor_id=v, amount_try=D("1000"), entry_date=date(2025, 3, 2))


def _alert_count(db, cid):
    return db.execute(select(func.count()).select_from(AIAlert).where(AIAlert.company_id == cid)).scalar_one()


def test_scan_is_idempotent_dedup(db, seed):
    cid = seed["a"]["company"].id
    _dup_pair(db, seed)
    db.commit()
    s1 = assurance.scan_company(db, cid)
    n1 = _alert_count(db, cid)
    s2 = assurance.scan_company(db, cid)
    n2 = _alert_count(db, cid)
    assert s1["created"] >= 1
    assert s2["created"] == 0
    assert n1 == n2


def test_dismissed_finding_not_recreated(db, seed):
    cid = seed["a"]["company"].id
    _dup_pair(db, seed)
    db.commit()
    assurance.scan_company(db, cid)
    a = db.execute(
        select(AIAlert).where(AIAlert.company_id == cid, AIAlert.dedup_key.isnot(None))
    ).scalars().first()
    a.is_dismissed = True
    a.dismissed_until = datetime.now(timezone.utc) + timedelta(days=7)
    db.commit()
    before = _alert_count(db, cid)
    assurance.scan_company(db, cid)
    assert _alert_count(db, cid) == before  # not re-nagged


def test_scan_company_isolation(db, seed):
    cid_a = seed["a"]["company"].id
    cid_b = seed["b"]["company"].id
    _dup_pair(db, seed, label="b")  # anomaly only in company B
    db.commit()
    assurance.scan_company(db, cid_a)  # scan A
    assert _alert_count(db, cid_a) == 0   # A is clean
    assert _alert_count(db, cid_b) == 0   # A's scan never wrote into B


def test_scan_leaves_money_untouched(db, seed, session_factory):
    """Mandatory §3.4 guard: a full scan must not alter any monetary value."""
    cid = seed["a"]["company"].id
    # A spread of anomalous + clean records across both tables.
    _dup_pair(db, seed)
    _cost(db, seed, amount_try=D("1000"), vat_amount_try=D("999"), total_with_vat_try=D("1999"))  # kdv
    _cost(db, seed, amount_usd=None)  # missing fx
    _cost(db, seed, vendor_id=None, subcontractor_id=None)  # unlinked
    _inv(db, seed, amount_try=D("0"), vat_amount_try=D("0"), total_with_vat_try=D("0"), net_due_try=D("0"))
    _inv(db, seed, amount_try=D("2000000"))  # over contract
    db.commit()

    def snapshot():
        s = session_factory()
        try:
            costs = {
                c.id: (c.amount_try, c.vat_amount_try, c.total_with_vat_try, c.amount_usd, c.amount_paid_try)
                for c in s.execute(select(CostEntry)).scalars()
            }
            invs = {
                i.id: (i.amount_try, i.vat_amount_try, i.total_with_vat_try, i.net_due_try,
                       i.amount_received_try, i.amount_usd)
                for i in s.execute(select(ClientInvoice)).scalars()
            }
            return costs, invs
        finally:
            s.close()

    before = snapshot()
    summary = assurance.scan_company(db, cid)
    after = snapshot()
    assert before == after  # byte-identical monetary data
    assert summary["total_found"] >= 4


# --- Endpoint -------------------------------------------------------------- #
def test_assurance_scan_endpoint(client, seed, db):
    _dup_pair(db, seed)
    db.commit()
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/ai/assurance/scan")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["total_found"] >= 1
    assert "scanned" in body and "found" in body and "created" in body


def test_assurance_findings_appear_in_alerts_list_with_linkage(client, seed, db):
    _dup_pair(db, seed)
    db.commit()
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    client.post("/api/v1/ai/assurance/scan")
    r = client.get("/api/v1/ai/alerts")
    assert r.status_code == 200
    findings = [a for a in r.json()["data"] if a.get("dedup_key")]
    assert findings
    assert findings[0]["source_type"] == "cost_entry"
    assert findings[0]["source_id"]
