"""CR-031-B: landowner_payments table (arsa sahibi ödeme defteri)

Revision ID: 0036_landowner_payments
Revises: 0035_unit_sales
Create Date: 2026-06-20

Additive only — no backfill. The landowner-contribution ledger for share revenue
models (kat karşılığı / hasılat). FX-at-date per CR-014 (amount_try + rate@
payment_date → amount_usd). Existing projects have no rows → zero behavior change
until used. Company-scoped + RLS + composite (company_id, project_id) index,
mirroring unit_sales (0035).

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32)).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_index, create_policy, create_table, enable_rls

revision = "0036_landowner_payments"
down_revision = "0035_unit_sales"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    create_table(
        "landowner_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("payer_name", sa.String(255), nullable=True),
        sa.Column("committed_total_try", sa.Numeric(18, 2), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount_try", sa.Numeric(18, 2), nullable=False),
        sa.Column("fx_rate_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column("amount_usd", sa.Numeric(18, 2), nullable=True),
        sa.Column("payment_type", sa.String(40), nullable=True),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index("ix_landowner_payments_company_project", "landowner_payments", ["company_id", "project_id"])
    create_index("ix_landowner_payments_project", "landowner_payments", ["project_id"])

    enable_rls("landowner_payments")
    create_policy("landowner_payments_company_isolation", "landowner_payments",
                  f"FOR ALL USING (company_id = {CURRENT_COMPANY})")
    create_policy("landowner_payments_hide_deleted", "landowner_payments",
                  "FOR SELECT USING (is_deleted = false)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS landowner_payments_hide_deleted ON landowner_payments;")
    op.execute("DROP POLICY IF EXISTS landowner_payments_company_isolation ON landowner_payments;")
    op.drop_index("ix_landowner_payments_project", table_name="landowner_payments")
    op.drop_index("ix_landowner_payments_company_project", table_name="landowner_payments")
    op.drop_table("landowner_payments")
