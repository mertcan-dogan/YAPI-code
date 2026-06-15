"""CR-008-H — vendor management endpoints: list+spend, suggestions, merge
(relink + audit), aliases, unlinked listing + link (§9.2)."""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.audit_log import AuditLog
from app.models.cost_entry import CostEntry
from app.models.vendor import Vendor, VendorAlias
from app.services import vendor_backfill as bf


def _cost(db, project, cid, uid, supplier, *, amount="1000"):
    c = CostEntry(
        project_id=project.id, company_id=cid, entry_date=date(2026, 1, 15),
        cost_category="material_concrete", supplier_name=supplier, amount_try=Decimal(amount),
        vat_amount_try=Decimal("0"), total_with_vat_try=Decimal(amount),
        payment_status="unpaid", entry_type="actual", created_by=uid,
    )
    db.add(c)
    db.flush()
    return c


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])


def _seed_and_backfill(db, seed, names):
    p, cid, uid = seed["a"]["project"], seed["a"]["company"].id, seed["a"]["users"][ROLE_DIRECTOR].id
    for n, amt in names:
        _cost(db, p, cid, uid, n, amount=amt)
    db.commit()
    bf.backfill_company(db, cid)
    return cid


# --------------------------------------------------------------------------- #
# List + spend
# --------------------------------------------------------------------------- #
def test_list_vendors_with_spend(client, seed, db):
    _seed_and_backfill(db, seed, [("Akçansa", "1000"), ("Akçansa A.Ş.", "2500"), ("Demir İnşaat", "4000")])
    _login(client, seed)
    r = client.get("/api/v1/vendors")
    assert r.status_code == 200, r.text
    rows = {v["canonical_name"]: v for v in r.json()["data"]}
    # Demir ranks first (4000 > 3500); Akçansa has 2 aliases and 3500 total.
    assert r.json()["data"][0]["canonical_name"] == "Demir İnşaat"
    ak = next(v for k, v in rows.items() if "Akçansa" in k)
    assert ak["total_try"] == "3500.00"
    assert ak["alias_count"] == 2
    assert ak["cost_entry_count"] == 2


def test_suggestions_flags_fuzzy(client, seed, db):
    _seed_and_backfill(db, seed, [("Bozkurt Beton", "1000"), ("Bozkurt Beotn", "2000")])
    _login(client, seed)
    r = client.get("/api/v1/vendors/suggestions")
    assert r.status_code == 200
    clusters = r.json()["data"]
    assert any(len(c) >= 2 for c in clusters)


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #
def test_merge_relinks_rows_and_audits(client, seed, db):
    cid = _seed_and_backfill(db, seed, [("Bozkurt Beton", "1000"), ("Bozkurt Beotn", "2000")])
    vendors = db.execute(select(Vendor).where(Vendor.company_id == cid, Vendor.is_deleted.is_(False))).scalars().all()
    by_name = {v.canonical_name: v for v in vendors}
    survivor = by_name["Bozkurt Beton"]
    merged = by_name["Bozkurt Beotn"]

    _login(client, seed)
    r = client.post("/api/v1/vendors/merge", json={"survivor_id": str(survivor.id), "merged_ids": [str(merged.id)]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["relinked_cost_entries"] == 1

    # The merged vendor is gone; spend now consolidates under the survivor.
    r2 = client.get("/api/v1/vendors")
    names = [v["canonical_name"] for v in r2.json()["data"]]
    assert "Bozkurt Beotn" not in names
    survivor_row = next(v for v in r2.json()["data"] if v["canonical_name"] == "Bozkurt Beton")
    assert survivor_row["total_try"] == "3000.00"

    # Audit row written for the merge.
    audits = db.execute(select(AuditLog).where(AuditLog.table_name == "vendors", AuditLog.action == "MERGE")).scalars().all()
    assert len(audits) == 1
    assert audits[0].record_id == survivor.id


def test_merge_rejects_foreign_vendor(client, seed, db):
    a_cid = _seed_and_backfill(db, seed, [("Akçansa", "1000")])
    # Company B vendor.
    b = seed["b"]
    _cost(db, b["project"], b["company"].id, b["users"][ROLE_DIRECTOR].id, "Beta Firma")
    db.commit()
    bf.backfill_company(db, b["company"].id)
    a_vendor = db.execute(select(Vendor).where(Vendor.company_id == a_cid)).scalars().first()
    b_vendor = db.execute(select(Vendor).where(Vendor.company_id == b["company"].id)).scalars().first()

    _login(client, seed)  # company A
    r = client.post("/api/v1/vendors/merge", json={"survivor_id": str(a_vendor.id), "merged_ids": [str(b_vendor.id)]})
    assert r.status_code == 404  # B's vendor not visible to A


def test_merge_survivor_in_merged_rejected(client, seed, db):
    cid = _seed_and_backfill(db, seed, [("Akçansa", "1000")])
    v = db.execute(select(Vendor).where(Vendor.company_id == cid)).scalars().first()
    _login(client, seed)
    r = client.post("/api/v1/vendors/merge", json={"survivor_id": str(v.id), "merged_ids": [str(v.id)]})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Aliases
# --------------------------------------------------------------------------- #
def test_add_and_remove_alias(client, seed, db):
    cid = _seed_and_backfill(db, seed, [("Akçansa", "1000")])
    v = db.execute(select(Vendor).where(Vendor.company_id == cid)).scalars().first()
    _login(client, seed)
    r = client.post(f"/api/v1/vendors/{v.id}/aliases", json={"alias_name": "Akçansa Çimento"})
    assert r.status_code == 200
    alias_id = r.json()["data"]["id"]

    listed = client.get(f"/api/v1/vendors/{v.id}/aliases").json()["data"]
    assert "Akçansa Çimento" in [a["alias_name"] for a in listed]

    assert client.delete(f"/api/v1/vendors/{v.id}/aliases/{alias_id}").status_code == 200
    listed2 = client.get(f"/api/v1/vendors/{v.id}/aliases").json()["data"]
    assert "Akçansa Çimento" not in [a["alias_name"] for a in listed2]


# --------------------------------------------------------------------------- #
# Unlinked + link
# --------------------------------------------------------------------------- #
def test_unlinked_and_link(client, seed, db):
    p, cid, uid = seed["a"]["project"], seed["a"]["company"].id, seed["a"]["users"][ROLE_DIRECTOR].id
    # One backfilled vendor + an unlinked legacy row.
    _cost(db, p, cid, uid, "Akçansa", amount="1000")
    db.commit()
    bf.backfill_company(db, cid)
    legacy = _cost(db, p, cid, uid, "Yeni Tedarikçi", amount="500")  # added after backfill, vendor_id NULL
    db.commit()
    assert legacy.vendor_id is None
    vendor = db.execute(select(Vendor).where(Vendor.company_id == cid)).scalars().first()

    _login(client, seed)
    unlinked = client.get("/api/v1/vendors/unlinked").json()["data"]
    assert "Yeni Tedarikçi" in [s["supplier_name"] for s in unlinked["suppliers"]]

    r = client.post(f"/api/v1/vendors/{vendor.id}/link", json={"supplier_names": ["Yeni Tedarikçi"]})
    assert r.status_code == 200
    assert r.json()["data"]["linked_cost_entries"] == 1

    db.refresh(legacy)
    assert legacy.vendor_id == vendor.id
    # Now nothing unlinked.
    assert client.get("/api/v1/vendors/unlinked").json()["data"]["suppliers"] == []


def test_vendors_require_auth(client):
    assert client.get("/api/v1/vendors").status_code == 401
    assert client.get("/api/v1/vendors/unlinked").status_code == 401


def test_vendors_company_isolation(client, seed, db):
    a_cid = _seed_and_backfill(db, seed, [("Akçansa", "1000")])
    # Company B sees none of A's vendors.
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.get("/api/v1/vendors").json()["data"] == []
