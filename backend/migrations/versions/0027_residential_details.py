"""CR-016-A: residential m² columns on projects + project_units (daire dağılımı)

Revision ID: 0027_residential_details
Revises: 0026_usd_snapshots
Create Date: 2026-06-16

Additive only — no backfill. ``projects`` gains two NULLABLE construction-area
columns; the new ``project_units`` table holds the unit schedule (one row per
unit type) that CR-017 will aggregate into per-m² benchmarks (§0.2). Existing
projects are untouched (the columns are NULL and the schedule is empty until
filled). Company-scoped + RLS, mirroring the vendors table (0022).

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32) — the
CR-007 0021 trap).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import add_column, create_index, create_policy, create_table, enable_rls

revision = "0027_residential_details"
down_revision = "0026_usd_snapshots"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    # --- project-level construction area (additive, nullable) ---
    add_column("projects", sa.Column("construction_gross_m2", sa.Numeric(12, 2), nullable=True))
    add_column("projects", sa.Column("construction_net_m2", sa.Numeric(12, 2), nullable=True))

    # --- project_units (the daire dağılımı / unit schedule) ---
    create_table(
        "project_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("unit_type", sa.String(20), nullable=False),
        sa.Column("custom_label", sa.String(100), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("gross_m2_each", sa.Numeric(10, 2), nullable=False),
        sa.Column("net_m2_each", sa.Numeric(10, 2), nullable=True),
        sa.Column("sale_price_try", sa.Numeric(18, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index("ix_project_units_project", "project_units", ["project_id"])
    create_index("ix_project_units_company", "project_units", ["company_id"])

    # --- RLS parity (defence in depth), mirroring vendors (0022) ---
    enable_rls("project_units")
    create_policy("project_units_company_isolation", "project_units",
                  f"FOR ALL USING (company_id = {CURRENT_COMPANY})")
    create_policy("project_units_hide_deleted", "project_units",
                  "FOR SELECT USING (is_deleted = false)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS project_units_hide_deleted ON project_units;")
    op.execute("DROP POLICY IF EXISTS project_units_company_isolation ON project_units;")
    op.drop_index("ix_project_units_company", table_name="project_units")
    op.drop_index("ix_project_units_project", table_name="project_units")
    op.drop_table("project_units")
    op.drop_column("projects", "construction_net_m2")
    op.drop_column("projects", "construction_gross_m2")
