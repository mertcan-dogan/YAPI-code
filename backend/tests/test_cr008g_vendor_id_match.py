"""CR-008-G — get_vendor_spend / compare_vendors prefer vendor_id + aliases.

Linked rows match exactly via vendor_id (primary path); unlinked legacy rows
still match via the CR-007 normalised/pg_trgm fallback; matched_names reports the
canonical name + aliases (§8.2).
"""
from datetime import date
from decimal import Decimal

import pytest

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.services import agent_tools as T
from app.services import vendor_backfill as bf


def _cost(db, project, cid, uid, supplier, *, amount="1000", date_=date(2026, 1, 15), category="material_concrete"):
    c = CostEntry(
        project_id=project.id, company_id=cid, entry_date=date_,
        cost_category=category, supplier_name=supplier, amount_try=Decimal(amount),
        vat_amount_try=Decimal("0"), total_with_vat_try=Decimal(amount),
        payment_status="unpaid", entry_type="actual", created_by=uid,
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture()
def ctx(seed):
    return {
        "cid": seed["a"]["company"].id,
        "project": seed["a"]["project"],
        "uid": seed["a"]["users"][ROLE_DIRECTOR].id,
    }


# --------------------------------------------------------------------------- #
# Exact vendor_id path after backfill
# --------------------------------------------------------------------------- #
def test_vendor_spend_via_vendor_id_exact_totals(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    # Two spellings that normalise to the same vendor.
    _cost(db, p, cid, uid, "Akçansa", amount="1000")
    _cost(db, p, cid, uid, "Akçansa A.Ş.", amount="2500")
    _cost(db, p, cid, uid, "Başka Firma", amount="9999")  # different vendor
    db.commit()
    bf.backfill_company(db, cid)

    out = T.get_vendor_spend(db, cid, vendor_name="Akçansa")
    s = out["summary"]
    assert s["total_try"] == "3500.00"               # both Akçansa spellings, exact
    assert s["invoice_count"] == 2
    # matched_names reports canonical + aliases, not a fuzzy raw list.
    assert s["vendor_name"] == s["matched_names"][0] or "Akçansa" in s["vendor_name"]
    assert "Akçansa" in s["matched_names"]
    assert "Akçansa A.Ş." in s["matched_names"]
    # Records are the vendor-linked rows.
    assert all(r["supplier_name"].startswith("Akçansa") for r in out["records"])


def test_vendor_spend_resolves_by_alias_spelling(db, ctx):
    """Querying with a non-canonical alias still resolves to the canonical vendor."""
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    _cost(db, p, cid, uid, "Akçansa", amount="1000")
    _cost(db, p, cid, uid, "Akçansa A.Ş.", amount="2500")
    db.commit()
    bf.backfill_company(db, cid)

    out = T.get_vendor_spend(db, cid, vendor_name="akçansa aş")  # different spelling, same norm
    assert out["summary"]["total_try"] == "3500.00"
    assert out["summary"]["invoice_count"] == 2


def test_vendor_spend_unlinked_legacy_still_matched(db, ctx):
    """A row added AFTER backfill (vendor_id NULL) still contributes via fallback."""
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    _cost(db, p, cid, uid, "Akçansa", amount="1000")
    db.commit()
    bf.backfill_company(db, cid)
    # New legacy row, not yet linked.
    legacy = _cost(db, p, cid, uid, "Akçansa", amount="500")
    db.commit()
    assert legacy.vendor_id is None

    out = T.get_vendor_spend(db, cid, vendor_name="Akçansa")
    assert out["summary"]["total_try"] == "1500.00"   # 1000 linked + 500 legacy
    assert out["summary"]["invoice_count"] == 2


def test_vendor_spend_no_double_count_when_linked(db, ctx):
    """A linked row whose supplier_name also matches the fallback is counted once."""
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    _cost(db, p, cid, uid, "Akçansa", amount="1000")
    db.commit()
    bf.backfill_company(db, cid)

    out = T.get_vendor_spend(db, cid, vendor_name="Akçansa")
    assert out["summary"]["invoice_count"] == 1
    assert out["summary"]["total_try"] == "1000.00"


def test_vendor_spend_fuzzy_variants_stay_separate(db, ctx):
    """After backfill, 'Bozkurt Beton' and 'Bozkurt Beotn' are distinct vendors —
    querying one returns only its own spend (merge is a separate CR-008-H action)."""
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    _cost(db, p, cid, uid, "Bozkurt Beton", amount="3000")
    _cost(db, p, cid, uid, "Bozkurt Beotn", amount="7000")
    db.commit()
    bf.backfill_company(db, cid)

    out = T.get_vendor_spend(db, cid, vendor_name="Bozkurt Beton")
    assert out["summary"]["total_try"] == "3000.00"      # not 10000 — not merged
    assert out["summary"]["matched_names"] == ["Bozkurt Beton"]


# --------------------------------------------------------------------------- #
# compare_vendors groups by canonical vendor name
# --------------------------------------------------------------------------- #
def test_compare_vendors_groups_by_canonical(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    _cost(db, p, cid, uid, "Akçansa", amount="1000")
    _cost(db, p, cid, uid, "Akçansa A.Ş.", amount="2000")   # same vendor after backfill
    _cost(db, p, cid, uid, "Demir İnşaat", amount="2500")
    db.commit()
    bf.backfill_company(db, cid)

    out = T.compare_vendors(db, cid)
    ranking = {r["vendor_name"]: r for r in out["summary"]["ranking"]}
    # Akçansa's two spellings collapse to one canonical entry totalling 3000.
    akcansa = next(r for k, r in ranking.items() if "Akçansa" in k)
    assert akcansa["total_try"] == "3000.00"
    assert akcansa["invoice_count"] == 2


def test_compare_vendors_legacy_unlinked_still_ranked(db, ctx):
    """Unlinked rows (no backfill) still rank by supplier name (CR-007 path)."""
    p, cid, uid = ctx["project"], ctx["cid"], ctx["uid"]
    _cost(db, p, cid, uid, "Akçansa", amount="5000")
    db.commit()  # no backfill -> vendor_id NULL
    out = T.compare_vendors(db, cid)
    assert out["summary"]["ranking"][0]["vendor_name"] == "Akçansa"
    assert out["summary"]["ranking"][0]["total_try"] == "5000.00"
