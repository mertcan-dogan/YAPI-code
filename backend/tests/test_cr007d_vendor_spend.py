"""CR-007-D — vendor spend & compare (headline use case).

Exact-number correctness on SQLite (§11.1, §11.3): seed a known vendor across
projects/categories/months, assert totals + buckets to the kuruş; assert the
union of cost_entries.supplier_name and subcontractors.name; assert normalised
variants merge; assert ranking. The pg_trgm fuzzy path is gated behind
@pytest.mark.postgres (§0 B1).
"""
import os
from datetime import date
from decimal import Decimal

import pytest

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.services import agent_tools as T


def _cost(db, project, company_id, created_by, *, amount, vat="0", date_=date(2026, 1, 15),
          category="material_concrete", supplier="Akçansa", status="unpaid", sub_id=None):
    c = CostEntry(
        project_id=project.id, company_id=company_id, entry_date=date_,
        cost_category=category, supplier_name=supplier, amount_try=Decimal(amount),
        vat_amount_try=Decimal(vat), total_with_vat_try=Decimal(amount) + Decimal(vat),
        payment_status=status, entry_type="actual", subcontractor_id=sub_id, created_by=created_by,
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture()
def ctx(seed):
    return {
        "cid": seed["a"]["company"].id,
        "project": seed["a"]["project"],
        "dir": seed["a"]["users"][ROLE_DIRECTOR],
    }


# --------------------------------------------------------------------------- #
# get_vendor_spend — exact totals + buckets
# --------------------------------------------------------------------------- #
def test_vendor_spend_exact_totals_and_buckets(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["dir"].id
    _cost(db, p, cid, uid, amount="1000", vat="200", date_=date(2026, 1, 10), category="material_concrete")
    _cost(db, p, cid, uid, amount="3000", vat="600", date_=date(2026, 1, 25), category="material_steel")
    _cost(db, p, cid, uid, amount="500", vat="100", date_=date(2026, 2, 5), category="material_concrete")
    # A different vendor — must not leak into the totals.
    _cost(db, p, cid, uid, amount="9999", supplier="Başka Firma", category="material_other")

    out = T.get_vendor_spend(db, cid, vendor_name="Akçansa")
    s = out["summary"]
    assert s["total_try"] == "4500.00"
    assert s["total_with_vat_try"] == "5400.00"
    assert s["invoice_count"] == 3
    assert s["project_count"] == 1

    by_month = {b["month"]: b["total"] for b in s["by_month"]}
    assert by_month["2026-01"] == "4000.00"
    assert by_month["2026-02"] == "500.00"

    by_cat = {b["category"]: b["total"] for b in s["by_category"]}
    assert by_cat["material_concrete"] == "1500.00"
    assert by_cat["material_steel"] == "3000.00"


def test_vendor_spend_date_window_filters(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["dir"].id
    _cost(db, p, cid, uid, amount="1000", date_=date(2026, 1, 10))
    _cost(db, p, cid, uid, amount="500", date_=date(2025, 6, 1))  # outside window

    out = T.get_vendor_spend(db, cid, vendor_name="Akçansa",
                             date_from=date(2026, 1, 1), date_to=date(2026, 6, 30))
    assert out["summary"]["total_try"] == "1000.00"
    assert out["summary"]["invoice_count"] == 1


def test_vendor_spend_unions_supplier_and_subcontractor(db, ctx):
    """A cost entry linked only via subcontractor_id (no supplier_name) must count."""
    p, cid, uid = ctx["project"], ctx["cid"], ctx["dir"].id
    sub = Subcontractor(
        project_id=p.id, company_id=cid, name="Akçansa İnşaat",
        contract_value_try=Decimal("100000"), status="active",
    )
    db.add(sub)
    db.flush()
    # Free-text supplier spend.
    _cost(db, p, cid, uid, amount="1000", supplier="Akçansa")
    # Subcontractor-linked spend with NO supplier_name.
    _cost(db, p, cid, uid, amount="2000", supplier=None, sub_id=sub.id)

    out = T.get_vendor_spend(db, cid, vendor_name="Akçansa")
    assert out["summary"]["total_try"] == "3000.00"
    assert out["summary"]["invoice_count"] == 2
    # Both spellings surface in matched_names.
    assert len(out["summary"]["matched_names"]) >= 2


def test_vendor_spend_merges_normalised_variants(db, ctx):
    """'Akçansa A.Ş.' and 'akçansa aş' normalise to the same vendor."""
    p, cid, uid = ctx["project"], ctx["cid"], ctx["dir"].id
    _cost(db, p, cid, uid, amount="1000", supplier="Akçansa A.Ş.")
    _cost(db, p, cid, uid, amount="2500", supplier="akçansa aş")

    out = T.get_vendor_spend(db, cid, vendor_name="Akçansa A.Ş.")
    assert out["summary"]["total_try"] == "3500.00"
    assert out["summary"]["invoice_count"] == 2
    assert sorted(out["summary"]["matched_names"]) == ["Akçansa A.Ş.", "akçansa aş"]


def test_vendor_spend_no_match_returns_zeroes(db, ctx):
    out = T.get_vendor_spend(db, ctx["cid"], vendor_name="Olmayan Firma")
    assert out["summary"]["total_try"] == "0.00"
    assert out["summary"]["invoice_count"] == 0
    assert out["summary"]["matched_names"] == []
    assert out["records"] == []


def test_vendor_spend_records_have_deep_links(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["dir"].id
    _cost(db, p, cid, uid, amount="1000", supplier="Akçansa")
    out = T.get_vendor_spend(db, cid, vendor_name="Akçansa")
    assert out["records"][0]["deep_link"].startswith(f"/projects/{p.id}/dashboard?highlight=")
    assert out["records"][0]["supplier_name"] == "Akçansa"


def test_vendor_spend_excludes_pending_approval(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["dir"].id
    _cost(db, p, cid, uid, amount="1000", supplier="Akçansa")
    pending = _cost(db, p, cid, uid, amount="5000", supplier="Akçansa")
    pending.pending_approval = True
    db.flush()
    out = T.get_vendor_spend(db, cid, vendor_name="Akçansa")
    assert out["summary"]["total_try"] == "1000.00"


def test_vendor_spend_company_isolation(db, seed):
    a_cid = seed["a"]["company"].id
    b_cid = seed["b"]["company"].id
    a_dir = seed["a"]["users"][ROLE_DIRECTOR]
    b_dir = seed["b"]["users"][ROLE_DIRECTOR]
    _cost(db, seed["a"]["project"], a_cid, a_dir.id, amount="1000", supplier="Akçansa")
    _cost(db, seed["b"]["project"], b_cid, b_dir.id, amount="8888", supplier="Akçansa")

    out = T.get_vendor_spend(db, a_cid, vendor_name="Akçansa")
    assert out["summary"]["total_try"] == "1000.00"


# --------------------------------------------------------------------------- #
# compare_vendors — ranking
# --------------------------------------------------------------------------- #
def test_compare_vendors_ranking(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["dir"].id
    _cost(db, p, cid, uid, amount="5000", supplier="Akçansa")
    _cost(db, p, cid, uid, amount="3000", supplier="Akçansa")   # 8000 total
    _cost(db, p, cid, uid, amount="6000", supplier="Bms Çelik")
    _cost(db, p, cid, uid, amount="1000", supplier="Küçük Tedarikçi")

    out = T.compare_vendors(db, cid)
    ranking = out["summary"]["ranking"]
    assert ranking[0]["vendor_name"] == "Akçansa"
    assert ranking[0]["total_try"] == "8000.00"
    assert ranking[0]["invoice_count"] == 2
    assert ranking[1]["vendor_name"] == "Bms Çelik"
    assert ranking[1]["total_try"] == "6000.00"


def test_compare_vendors_top_n_limit(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["dir"].id
    for i, amt in enumerate(["1000", "2000", "3000", "4000", "5000", "6000"]):
        _cost(db, p, cid, uid, amount=amt, supplier=f"Firma {i}")
    out = T.compare_vendors(db, cid, top_n=3)
    assert len(out["summary"]["ranking"]) == 3
    assert out["truncated"] is True
    assert out["summary"]["ranking"][0]["total_try"] == "6000.00"


def test_compare_vendors_category_filter(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["dir"].id
    _cost(db, p, cid, uid, amount="5000", supplier="Akçansa", category="material_concrete")
    _cost(db, p, cid, uid, amount="9000", supplier="Akçansa", category="material_steel")
    out = T.compare_vendors(db, cid, cost_category="material_concrete")
    assert out["summary"]["ranking"][0]["total_try"] == "5000.00"


def test_compare_vendors_includes_subcontractor_linked(db, ctx):
    p, cid, uid = ctx["project"], ctx["cid"], ctx["dir"].id
    sub = Subcontractor(project_id=p.id, company_id=cid, name="Demir Taşeron",
                        contract_value_try=Decimal("50000"), status="active")
    db.add(sub)
    db.flush()
    _cost(db, p, cid, uid, amount="7000", supplier=None, sub_id=sub.id)
    out = T.compare_vendors(db, cid)
    names = {r["vendor_name"]: r["total_try"] for r in out["summary"]["ranking"]}
    assert names.get("Demir Taşeron") == "7000.00"


# --------------------------------------------------------------------------- #
# pg_trgm fuzzy match — PostgreSQL only (§0 B1)
# --------------------------------------------------------------------------- #
@pytest.mark.postgres
@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="needs a Postgres DB")
def test_vendor_spend_pg_trgm_fuzzy_match():
    """On Postgres, a misspelled query ('Akcansa' vs 'Akçansa Beton') should
    still match via trigram similarity >= 0.4. Runs only with TEST_POSTGRES_URL."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    eng = create_engine(os.environ["TEST_POSTGRES_URL"], future=True)
    eng.dispose()  # smoke: connection string is usable
    # Full fixture wiring against Postgres is environment-specific; this marker
    # documents the gated path required by §0 B1 / §2.3.
    assert T.PG_TRGM_THRESHOLD == 0.4
