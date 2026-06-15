"""CR-008-F — conservative vendor backfill.

Exact normalised matches → one canonical vendor + aliases + linked rows; fuzzy
variants are FLAGGED, never auto-merged; idempotent; company-isolated (§7.2).
"""
from datetime import date
from decimal import Decimal

import pytest

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.models.vendor import Vendor, VendorAlias
from app.services import vendor_backfill as bf


def _cost(db, project, cid, uid, supplier, *, amount="1000"):
    c = CostEntry(
        project_id=project.id, company_id=cid, entry_date=date(2026, 1, 15),
        cost_category="material_concrete", supplier_name=supplier,
        amount_try=Decimal(amount), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal(amount), payment_status="unpaid",
        entry_type="actual", created_by=uid,
    )
    db.add(c)
    db.flush()
    return c


def _sub(db, project, cid, name):
    s = Subcontractor(project_id=project.id, company_id=cid, name=name,
                      contract_value_try=Decimal("50000"), status="active")
    db.add(s)
    db.flush()
    return s


@pytest.fixture()
def ctx(seed):
    return {
        "cid": seed["a"]["company"].id,
        "project": seed["a"]["project"],
        "uid": seed["a"]["users"][ROLE_DIRECTOR].id,
    }


def _vendors(db, cid):
    return db.execute(
        Vendor.__table__.select().where(Vendor.company_id == cid)
    ).fetchall()


# --------------------------------------------------------------------------- #
# Exact normalised matches → canonical vendor + aliases + links
# --------------------------------------------------------------------------- #
def test_backfill_creates_vendors_aliases_and_links(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    # "Akçansa" and "Akçansa A.Ş." normalise to the SAME vendor (A.Ş. stripped).
    c1 = _cost(db, p, cid, uid, "Akçansa")
    c2 = _cost(db, p, cid, uid, "Akçansa A.Ş.")
    c3 = _cost(db, p, cid, uid, "Demir İnşaat")
    db.commit()

    summary = bf.backfill_company(db, cid)

    assert summary["vendors_created"] == 2          # Akçansa, Demir İnşaat
    assert summary["cost_entries_linked"] == 3
    # Both Akçansa spellings collapse to one vendor, with two aliases.
    vendors = db.execute(
        Vendor.__table__.select().where(Vendor.company_id == cid)
    ).fetchall()
    assert len(vendors) == 2

    for c in (c1, c2, c3):
        db.refresh(c)
    assert c1.vendor_id == c2.vendor_id           # same canonical vendor
    assert c3.vendor_id != c1.vendor_id
    akcansa_aliases = db.execute(
        VendorAlias.__table__.select().where(VendorAlias.vendor_id == c1.vendor_id)
    ).fetchall()
    assert {a.alias_name for a in akcansa_aliases} == {"Akçansa", "Akçansa A.Ş."}


def test_backfill_unions_cost_and_subcontractor(db, ctx):
    p, cid = ctx["project"], ctx["cid"]
    c = _cost(db, p, cid, ctx["uid"], "Demir Ltd")
    s = _sub(db, p, cid, "Demir Ltd.")   # normalises to the same "DEMIR"
    db.commit()

    bf.backfill_company(db, cid)
    db.refresh(c)
    db.refresh(s)
    assert c.vendor_id is not None
    assert c.vendor_id == s.vendor_id            # one vendor across both sources


def test_backfill_is_idempotent(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    _cost(db, p, cid, uid, "Akçansa")
    _cost(db, p, cid, uid, "Demir İnşaat")
    db.commit()

    first = bf.backfill_company(db, cid)
    assert first["vendors_created"] == 2

    second = bf.backfill_company(db, cid)
    assert second["vendors_created"] == 0
    assert second["aliases_created"] == 0
    assert second["cost_entries_linked"] == 0
    assert second["subcontractors_linked"] == 0
    # No duplicate vendors on re-run.
    assert len(db.execute(Vendor.__table__.select().where(Vendor.company_id == cid)).fetchall()) == 2


# --------------------------------------------------------------------------- #
# Fuzzy variants are FLAGGED, not auto-merged
# --------------------------------------------------------------------------- #
def test_backfill_flags_fuzzy_clusters_without_merging(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    _cost(db, p, cid, uid, "Bozkurt Beton")
    _cost(db, p, cid, uid, "Bozkurt Beotn")   # typo — different normalised name
    db.commit()

    summary = bf.backfill_company(db, cid)

    # Two SEPARATE vendors (not merged)…
    assert summary["vendors_created"] == 2
    # …but flagged as a likely-duplicate cluster for human review.
    assert summary["clusters_flagged"] >= 1
    flagged_names = {v["canonical_name"] for cluster in summary["clusters"] for v in cluster}
    assert {"Bozkurt Beton", "Bozkurt Beotn"} <= flagged_names


def test_distinct_vendors_not_clustered(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    _cost(db, p, cid, uid, "Akçansa")
    _cost(db, p, cid, uid, "Trabzon Belediyesi")
    db.commit()

    summary = bf.backfill_company(db, cid)
    assert summary["vendors_created"] == 2
    assert summary["clusters_flagged"] == 0   # clearly different names


# --------------------------------------------------------------------------- #
# Company isolation
# --------------------------------------------------------------------------- #
def test_backfill_company_isolation(db, seed):
    a_cid = seed["a"]["company"].id
    b_cid = seed["b"]["company"].id
    _cost(db, seed["a"]["project"], a_cid, seed["a"]["users"][ROLE_DIRECTOR].id, "Akçansa")
    _cost(db, seed["b"]["project"], b_cid, seed["b"]["users"][ROLE_DIRECTOR].id, "Başka Firma")
    db.commit()

    bf.backfill_company(db, a_cid)
    # Only company A got vendors; B untouched.
    assert len(db.execute(Vendor.__table__.select().where(Vendor.company_id == a_cid)).fetchall()) == 1
    assert len(db.execute(Vendor.__table__.select().where(Vendor.company_id == b_cid)).fetchall()) == 0


def test_backfill_skips_already_linked_rows(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    c = _cost(db, p, cid, uid, "Akçansa")
    db.commit()
    bf.backfill_company(db, cid)
    db.refresh(c)
    first_vendor = c.vendor_id
    assert first_vendor is not None

    # Add another row for the same vendor; re-run links only the new one.
    c2 = _cost(db, p, cid, uid, "Akçansa")
    db.commit()
    summary = bf.backfill_company(db, cid)
    db.refresh(c2)
    assert summary["cost_entries_linked"] == 1   # only the new row
    assert c2.vendor_id == first_vendor
