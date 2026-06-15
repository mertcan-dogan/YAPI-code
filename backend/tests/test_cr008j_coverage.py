"""CR-008-J — test-plan gap coverage + regression backstop (§11).

Rounds out items not already covered by the A/B/E/F/G/H/I suites:
- nullable vendor_id FK leaves existing-style rows untouched (§11.2)
- pinned chart snapshot re-validates identically (§11.1)
- vendor resolution / aliases are company-scoped (§11.3)
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.models.vendor import Vendor, VendorAlias
from app.schemas.chart import ChartSpec
from app.services import agent_tools as T
from app.services import vendor_backfill as bf

CHART = {
    "chart_type": "line", "title": "Akçansa Aylık", "x_key": "month",
    "series": [{"key": "total", "label": "Toplam", "type": "line"}],
    "data": [{"month": "2026-01", "total": 1000}],
    "currency": "TRY", "source_note": "kaynak",
}


# --------------------------------------------------------------------------- #
# §11.2 — additive nullable FK leaves existing rows untouched
# --------------------------------------------------------------------------- #
def test_vendor_id_is_nullable_and_defaults_none(db, seed):
    p, cid, uid = seed["a"]["project"], seed["a"]["company"].id, seed["a"]["users"][ROLE_DIRECTOR].id
    c = CostEntry(
        project_id=p.id, company_id=cid, entry_date=date(2026, 1, 1), cost_category="other",
        supplier_name="X", amount_try=Decimal("100"), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal("100"), payment_status="unpaid", entry_type="actual", created_by=uid,
    )
    s = Subcontractor(project_id=p.id, company_id=cid, name="Y", contract_value_try=Decimal("1000"), status="active")
    db.add_all([c, s])
    db.commit()
    db.refresh(c)
    db.refresh(s)
    # Existing-style inserts (no vendor_id) are valid and default to NULL.
    assert c.vendor_id is None
    assert s.vendor_id is None


# --------------------------------------------------------------------------- #
# §11.1 — pinned chart snapshot re-validates identically (re-renders the same)
# --------------------------------------------------------------------------- #
def test_pinned_chart_payload_revalidates_identically(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    stored = client.post(
        "/api/v1/workspace/items", json={"title": "G", "item_type": "chart", "payload": CHART}
    ).json()["data"]["payload"]
    # Re-running the same CR-007-C validation on the stored snapshot is a no-op:
    # the payload is already normalised, so it round-trips byte-for-byte.
    assert ChartSpec(**stored).model_dump() == stored


# --------------------------------------------------------------------------- #
# §11.3 — vendor resolution + aliases are company-scoped
# --------------------------------------------------------------------------- #
def _cost(db, project, cid, uid, supplier):
    c = CostEntry(
        project_id=project.id, company_id=cid, entry_date=date(2026, 1, 15), cost_category="material_concrete",
        supplier_name=supplier, amount_try=Decimal("1000"), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal("1000"), payment_status="unpaid", entry_type="actual", created_by=uid,
    )
    db.add(c)
    db.flush()


def test_vendor_resolution_is_company_scoped(db, seed):
    a_cid = seed["a"]["company"].id
    b_cid = seed["b"]["company"].id
    _cost(db, seed["a"]["project"], a_cid, seed["a"]["users"][ROLE_DIRECTOR].id, "Akçansa")
    db.commit()
    bf.backfill_company(db, a_cid)

    # Company A resolves Akçansa to its vendor and has spend.
    a_out = T.get_vendor_spend(db, a_cid, vendor_name="Akçansa")
    assert a_out["summary"]["total_try"] == "1000.00"
    # Company B has no Akçansa vendor/rows → resolves to nothing, zero spend.
    assert T._resolve_vendor(db, b_cid, "Akçansa") is None
    b_out = T.get_vendor_spend(db, b_cid, vendor_name="Akçansa")
    assert b_out["summary"]["total_try"] == "0.00"
    assert b_out["summary"]["matched_names"] == []


def test_backfill_aliases_are_company_scoped(db, seed):
    a_cid = seed["a"]["company"].id
    b_cid = seed["b"]["company"].id
    _cost(db, seed["a"]["project"], a_cid, seed["a"]["users"][ROLE_DIRECTOR].id, "Akçansa")
    db.commit()
    bf.backfill_company(db, a_cid)

    assert db.execute(select(VendorAlias).where(VendorAlias.company_id == a_cid)).scalars().all()
    assert db.execute(select(VendorAlias).where(VendorAlias.company_id == b_cid)).scalars().all() == []
    assert db.execute(select(Vendor).where(Vendor.company_id == b_cid)).scalars().all() == []
