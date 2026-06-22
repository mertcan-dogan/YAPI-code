"""CR-008-F (follow-up) — vendor auto-link at create/import time + non-transitive
merge suggestions.

Two fixes:
  * ``resolve_or_create_vendor_id`` links a freshly created cost/subcontractor row
    to a canonical vendor (or creates one) so rows no longer pile up vendor_id NULL
    until the one-time backfill is re-run.
  * ``find_duplicate_clusters`` is now PAIRWISE at a conservative threshold — the
    old 0.4 + union-find chained unrelated vendors into one giant cluster.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.models.vendor import Vendor, VendorAlias
from app.services import vendor_backfill as bf


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])


# --------------------------------------------------------------------------- #
# resolve_or_create_vendor_id
# --------------------------------------------------------------------------- #
def test_resolve_creates_then_links_idempotently(db, seed):
    cid = seed["a"]["company"].id

    v1 = bf.resolve_or_create_vendor_id(db, cid, "Akçansa Çimento")
    db.flush()
    assert v1 is not None
    # Same firm, different spelling/suffix -> SAME vendor (no duplicate).
    v2 = bf.resolve_or_create_vendor_id(db, cid, "AKÇANSA ÇİMENTO A.Ş.")
    assert v2 == v1
    vendors = db.execute(select(Vendor).where(Vendor.company_id == cid)).scalars().all()
    assert len(vendors) == 1
    # A blank name links to nothing.
    assert bf.resolve_or_create_vendor_id(db, cid, "   ") is None
    assert bf.resolve_or_create_vendor_id(db, cid, None) is None


def test_resolve_reuses_backfilled_vendor(db, seed):
    """A name already known to the backfill (alias exists) links, never duplicates."""
    cid = seed["a"]["company"].id
    existing = Vendor(company_id=cid, canonical_name="Demir İnşaat")
    db.add(existing)
    db.flush()
    db.add(VendorAlias(vendor_id=existing.id, company_id=cid,
                       alias_name="Demir İnşaat",
                       alias_normalised=bf.normalize_vendor_name("Demir İnşaat")))
    db.flush()

    vid = bf.resolve_or_create_vendor_id(db, cid, "demir inşaat ltd.")
    assert vid == existing.id
    assert len(db.execute(select(Vendor).where(Vendor.company_id == cid)).scalars().all()) == 1


# --------------------------------------------------------------------------- #
# Auto-link through the real create-cost endpoint
# --------------------------------------------------------------------------- #
def test_create_cost_auto_links_vendor(client, db, seed):
    _login(client, seed)
    pid = seed["a"]["project"].id
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2026-02-01", "cost_category": "material_concrete",
        "amount_try": "1000", "supplier_name": "Yılmaz Nakliyat",
    })
    assert r.status_code == 200, r.text
    cost_id = r.json()["data"]["id"]
    cost = db.get(CostEntry, cost_id)
    assert cost.vendor_id is not None
    vendor = db.get(Vendor, cost.vendor_id)
    assert vendor is not None and vendor.canonical_name == "Yılmaz Nakliyat"

    # A second cost with a variant spelling links to the SAME vendor.
    r2 = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2026-02-02", "cost_category": "material_concrete",
        "amount_try": "500", "supplier_name": "YILMAZ NAKLİYAT LTD.",
    })
    assert r2.status_code == 200, r2.text
    cost2 = db.get(CostEntry, r2.json()["data"]["id"])
    assert cost2.vendor_id == cost.vendor_id


def test_create_cost_without_supplier_leaves_vendor_null(client, db, seed):
    _login(client, seed)
    pid = seed["a"]["project"].id
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2026-02-01", "cost_category": "other", "amount_try": "1000",
    })
    assert r.status_code == 200, r.text
    cost = db.get(CostEntry, r.json()["data"]["id"])
    assert cost.vendor_id is None


# --------------------------------------------------------------------------- #
# Non-transitive merge suggestions (the mega-cluster bug)
# --------------------------------------------------------------------------- #
def test_suggestions_do_not_chain_unrelated_vendors(db, seed):
    """Distinct vendors that the old 0.4 + union-find chained into one mega-cluster
    must now produce only small, individually-reviewable pairs (never one giant
    group, never every vendor lumped together)."""
    cid = seed["a"]["company"].id
    names = ["Akçansa Çimento", "Bozkurt Beton", "Demir İnşaat", "Yılmaz Nakliyat",
             "Set Beton", "Oyak Beton", "Trabzon Belediyesi", "Karadeniz Elektrik"]
    for nm in names:
        db.add(Vendor(company_id=cid, canonical_name=nm))
    db.flush()

    clusters = bf.find_duplicate_clusters(db, cid)
    # No cluster contains more than 2 vendors (pairwise, not transitive).
    assert all(len(c) == 2 for c in clusters)
    # Nothing close to "everything in one group".
    assert all(len(c) < len(names) for c in clusters)
    flat = [m["canonical_name"] for c in clusters for m in c]
    # Unrelated names like these never get grouped at the conservative threshold.
    assert "Trabzon Belediyesi" not in flat
    assert "Karadeniz Elektrik" not in flat


def test_suggestions_still_flag_genuine_typos(db, seed):
    cid = seed["a"]["company"].id
    for nm in ["Bozkurt Beton", "Bozkurt Beotn"]:
        db.add(Vendor(company_id=cid, canonical_name=nm))
    db.flush()
    clusters = bf.find_duplicate_clusters(db, cid)
    assert len(clusters) == 1
    names = {m["canonical_name"] for m in clusters[0]}
    assert names == {"Bozkurt Beton", "Bozkurt Beotn"}
