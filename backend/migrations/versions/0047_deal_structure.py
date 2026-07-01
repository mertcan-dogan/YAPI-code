"""Per-project deal structure + planned unit owner side (CR-053)

Revision ID: 0047_deal_structure
Revises: 0046_skills
Create Date: 2026-07-01

Additive only — two new nullable / server-default columns on EXISTING
company-scoped tables, backing the operator-model deal setting (CR-053):

* ``projects.deal_structure`` (nullable String) — the founder's per-project
  arrangement (arsa_karsiligi_daire / kentsel_donusum / nakit_katki /
  yap_sat_kendi_arsa / diger). Documents the deal and drives UI labels/hints;
  it does NOT compute the P&L (correctness is DATA-DRIVEN, §0), so a NULL on an
  existing project behaves exactly as today's sell-side except the §3 revenue
  correction (which is data-driven, not enum-driven) applies.
* ``project_units.owner_side`` (String, server_default 'yuklenici') — tags each
  planned daire as the contractor's sellable stock or the landowner's share,
  mirroring ``unit_sales.owner_side``. Existing rows backfill to 'yuklenici'
  (today's behaviour: every planned unit is the contractor's), so nothing moves.

NO NEW RLS: both tables are already company-scoped with their existing isolation
policies (projects since the 0001 baseline, project_units since 0027); adding a
column changes no row's company_id and needs no new policy. NO new GRANTs (same
rationale as every additive migration since the role cutover — request-session
DML is auto-granted via ALTER DEFAULT PRIVILEGES).

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32)).
Migrations only run on Postgres (run_migrations skips non-Postgres URLs); the
SQLite test suite builds these tables via Base.metadata.create_all instead, so
the new columns appear automatically there. ``add_column`` is idempotent (skipped
when the column already exists), so ``alembic upgrade head`` converges any
database state — fresh, partially migrated, or fully built.
"""
import sqlalchemy as sa
from alembic import op

from migrations.idempotent import add_column

revision = "0047_deal_structure"
down_revision = "0046_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column("projects", sa.Column("deal_structure", sa.String(40), nullable=True))
    add_column(
        "project_units",
        sa.Column("owner_side", sa.String(20), nullable=False, server_default="yuklenici"),
    )


def downgrade() -> None:
    op.drop_column("project_units", "owner_side")
    op.drop_column("projects", "deal_structure")
