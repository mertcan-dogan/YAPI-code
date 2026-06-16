"""CR-018-A: cost subcategories — parent_category on custom_cost_categories

Revision ID: 0028_cost_subcategories
Revises: 0027_residential_details
Create Date: 2026-06-16

Additive: custom_cost_categories gains a NULLABLE ``parent_category`` (NULL =
top-level custom category, today's behavior; a COST_CATEGORY key = a custom
subcategory under that category). The unique constraint moves from
(company_id, name_normalized) to (company_id, parent_category, name_normalized)
so the same sub-name can exist under different parents. No cost-entry backfill;
``cost_entries.subcategory`` stays free-text. Existing customs get parent NULL.

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32) — the
CR-007 0021 trap). The constraint swap is Postgres-only (prod); the SQLite test DB
is built from the ORM models via create_all, which already carry the new shape.
"""
import sqlalchemy as sa
from alembic import op

from migrations.idempotent import add_column

revision = "0028_cost_subcategories"
down_revision = "0027_residential_details"
branch_labels = None
depends_on = None

OLD_UQ = "uq_custom_cat_company_name"
NEW_UQ = "uq_custom_cat_company_parent_name"
TABLE = "custom_cost_categories"


def upgrade() -> None:
    add_column(TABLE, sa.Column("parent_category", sa.String(length=50), nullable=True))

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite/test schema comes from the ORM models (create_all)
    uniques = {uc["name"] for uc in sa.inspect(bind).get_unique_constraints(TABLE)}
    if OLD_UQ in uniques:
        op.drop_constraint(OLD_UQ, TABLE, type_="unique")
    if NEW_UQ not in uniques:
        op.create_unique_constraint(
            NEW_UQ, TABLE, ["company_id", "parent_category", "name_normalized"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        uniques = {uc["name"] for uc in sa.inspect(bind).get_unique_constraints(TABLE)}
        if NEW_UQ in uniques:
            op.drop_constraint(NEW_UQ, TABLE, type_="unique")
        if OLD_UQ not in uniques:
            op.create_unique_constraint(OLD_UQ, TABLE, ["company_id", "name_normalized"])
    op.drop_column(TABLE, "parent_category")
