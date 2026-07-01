"""CR-031-A: unit_sales table (daire satış kaydı / sales register)

Revision ID: 0035_unit_sales
Revises: 0034_perf_indexes
Create Date: 2026-06-20

Additive only — no backfill. The sell-side revenue lane: one row per unit sale
for developer/seller revenue models (kat karşılığı / yap-sat / hasılat). FX-at-
date per CR-014 (sale_price_try + rate@sale_date → sale_price_usd). Existing
projects have no rows → zero behavior change until used. Company-scoped + RLS +
composite (company_id, project_id) index, mirroring project_units (0027).

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32)).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_index, create_policy, create_table, enable_rls

revision = "0035_unit_sales"
down_revision = "0034_perf_indexes"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    create_table(
        "unit_sales",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("project_unit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("project_units.id"), nullable=True),
        sa.Column("unit_label", sa.String(120), nullable=False),
        sa.Column("unit_type", sa.String(40), nullable=True),
        sa.Column("floor", sa.String(40), nullable=True),
        sa.Column("gross_m2", sa.Numeric(10, 2), nullable=True),
        sa.Column("net_m2", sa.Numeric(10, 2), nullable=True),
        sa.Column("buyer_name", sa.String(255), nullable=True),
        sa.Column("sale_price_try", sa.Numeric(18, 2), nullable=False),
        sa.Column("sale_date", sa.Date(), nullable=False),
        sa.Column("fx_rate_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column("sale_price_usd", sa.Numeric(18, 2), nullable=True),
        sa.Column("payment_type", sa.String(40), nullable=True),
        sa.Column("installment_note", sa.String(255), nullable=True),
        sa.Column("deed_status", sa.String(40), nullable=True),
        sa.Column("deed_date", sa.Date(), nullable=True),
        sa.Column("owner_side", sa.String(20), server_default="yuklenici", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index("ix_unit_sales_company_project", "unit_sales", ["company_id", "project_id"])
    create_index("ix_unit_sales_project", "unit_sales", ["project_id"])

    enable_rls("unit_sales")
    create_policy("unit_sales_company_isolation", "unit_sales",
                  f"FOR ALL USING (company_id = {CURRENT_COMPANY})")
    create_policy("unit_sales_hide_deleted", "unit_sales",
                  "FOR SELECT USING (is_deleted = false)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS unit_sales_hide_deleted ON unit_sales;")
    op.execute("DROP POLICY IF EXISTS unit_sales_company_isolation ON unit_sales;")
    op.drop_index("ix_unit_sales_project", table_name="unit_sales")
    op.drop_index("ix_unit_sales_company_project", table_name="unit_sales")
    op.drop_table("unit_sales")
