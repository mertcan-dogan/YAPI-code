"""KPI history snapshots for dashboard sparklines + month-over-month deltas

Revision ID: 0014_kpi_snapshots
Revises: 0013_reconcile_missing_columns
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_table, enable_rls

revision = "0014_kpi_snapshots"
down_revision = "0013_reconcile_missing_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table(
        "kpi_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("active_project_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_contract_value_try", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("weighted_avg_margin_pct", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("overdue_payment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # One snapshot per company per day (idempotent: IF NOT EXISTS).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_kpi_snapshot_company_date "
        "ON kpi_snapshots (company_id, snapshot_date)"
    )
    # Backend connects via a direct DB role (not PostgREST); enable RLS with no
    # policy so the table is never exposed through the public PostgREST API.
    enable_rls("kpi_snapshots")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_kpi_snapshot_company_date")
    op.drop_table("kpi_snapshots")
