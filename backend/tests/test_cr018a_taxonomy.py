"""CR-018-A: cost subcategory taxonomy + custom_cost_categories.parent_category.

Taxonomy is global (constants); custom subcategories reuse custom_cost_categories
with a nullable parent_category. SQLite-backed (the schema comes from the ORM
models via create_all, so the new column + unique constraint are exercised here).
"""
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.constants import (
    COST_CATEGORY_KEYS,
    COST_SUBCATEGORIES,
    subcategories_for,
)
from app.models.custom_category import CustomCostCategory


# --------------------------------------------------------------------------- #
# Preset taxonomy
# --------------------------------------------------------------------------- #
def test_subcategories_for_returns_presets():
    subs = subcategories_for("labour_direct")
    keys = [k for k, _ in subs]
    assert "elektrik" in keys
    assert "sihhi_tesisat" in keys
    assert "boya_badana" in keys
    # ordered list of (subkey, label) tuples
    assert all(isinstance(t, tuple) and len(t) == 2 for t in subs)


def test_subcategories_for_unknown_category_returns_empty():
    assert subcategories_for("does_not_exist") == []


def test_every_subcategory_key_is_a_valid_cost_category():
    # The §4 invariant: no orphan taxonomy entries.
    for key in COST_SUBCATEGORIES:
        assert key in COST_CATEGORY_KEYS, f"{key} is not a valid COST_CATEGORY key"


def test_every_category_has_a_taxonomy_entry():
    # Each standard category is represented (possibly with an empty preset list).
    for key in COST_CATEGORY_KEYS:
        assert key in COST_SUBCATEGORIES


def test_subkeys_unique_within_each_category():
    for key, subs in COST_SUBCATEGORIES.items():
        subkeys = [s for s, _ in subs]
        assert len(subkeys) == len(set(subkeys)), f"duplicate subkey in {key}"


def test_labels_are_nonempty_strings():
    for subs in COST_SUBCATEGORIES.values():
        for subkey, label in subs:
            assert isinstance(subkey, str) and subkey
            assert isinstance(label, str) and label.strip()


def test_labour_direct_and_sub_share_the_same_trade_list():
    assert subcategories_for("labour_direct") == subcategories_for("labour_sub")


def test_categories_without_presets_are_empty_not_missing():
    assert subcategories_for("contingency") == []
    assert subcategories_for("other") == []


def test_material_categories_have_relevant_presets():
    assert any(k == "hazir_beton" for k, _ in subcategories_for("material_concrete"))
    assert any(k == "nervurlu_demir" for k, _ in subcategories_for("material_steel"))


# --------------------------------------------------------------------------- #
# Schema: parent_category column + unique constraint
# --------------------------------------------------------------------------- #
def test_parent_category_column_added_nullable(engine):
    cols = {c["name"]: c for c in inspect(engine).get_columns("custom_cost_categories")}
    assert "parent_category" in cols
    assert cols["parent_category"]["nullable"]


def test_unique_constraint_includes_parent_category(engine):
    uniques = inspect(engine).get_unique_constraints("custom_cost_categories")
    cols_sets = [set(uc["column_names"]) for uc in uniques]
    assert {"company_id", "parent_category", "name_normalized"} in cols_sets


# --------------------------------------------------------------------------- #
# Custom subcategories (DB-level semantics)
# --------------------------------------------------------------------------- #
def test_custom_subcategory_persists_with_parent(seed, db):
    cid = seed["a"]["company"].id
    db.add(CustomCostCategory(
        company_id=cid, parent_category="labour_direct",
        name="Asma Tavan", name_normalized="asma tavan",
    ))
    db.commit()
    row = db.query(CustomCostCategory).filter_by(company_id=cid, name_normalized="asma tavan").one()
    assert row.parent_category == "labour_direct"


def test_top_level_custom_has_null_parent(seed, db):
    cid = seed["a"]["company"].id
    db.add(CustomCostCategory(company_id=cid, name="Özel Kategori", name_normalized="özel kategori"))
    db.commit()
    row = db.query(CustomCostCategory).filter_by(company_id=cid, name_normalized="özel kategori").one()
    assert row.parent_category is None  # unchanged CR-001-D behavior


def test_same_subname_allowed_under_different_parents(seed, db):
    cid = seed["a"]["company"].id
    db.add(CustomCostCategory(company_id=cid, parent_category="labour_direct", name="Özel", name_normalized="özel"))
    db.add(CustomCostCategory(company_id=cid, parent_category="material_other", name="Özel", name_normalized="özel"))
    db.commit()  # no violation — different parents
    rows = db.query(CustomCostCategory).filter_by(company_id=cid, name_normalized="özel").all()
    assert {r.parent_category for r in rows} == {"labour_direct", "material_other"}


def test_duplicate_subname_same_parent_rejected(seed, db):
    cid = seed["a"]["company"].id
    db.add(CustomCostCategory(company_id=cid, parent_category="labour_direct", name="Tekrar", name_normalized="tekrar"))
    db.commit()
    db.add(CustomCostCategory(company_id=cid, parent_category="labour_direct", name="Tekrar", name_normalized="tekrar"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
