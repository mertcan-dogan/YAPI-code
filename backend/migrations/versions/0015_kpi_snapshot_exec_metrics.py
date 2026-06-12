"""Add executive metrics to kpi_snapshots (backlog, projected profit, receivables, cash)

Revision ID: 0015_kpi_snapshot_exec_metrics
Revises: 0014_kpi_snapshots
Create Date: 2026-06-12
"""
import sqlalchemy as sa

from migrations.idempotent import add_column

revision = "0015_kpi_snapshot_exec_metrics"
down_revision = "0014_kpi_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column("kpi_snapshots", sa.Column("backlog_try", sa.Numeric(18, 2), nullable=False, server_default="0"))
    add_column("kpi_snapshots", sa.Column("projected_profit_try", sa.Numeric(18, 2), nullable=False, server_default="0"))
    add_column("kpi_snapshots", sa.Column("total_receivables_try", sa.Numeric(18, 2), nullable=False, server_default="0"))
    add_column("kpi_snapshots", sa.Column("net_cash_position_try", sa.Numeric(18, 2), nullable=False, server_default="0"))


def downgrade() -> None:
    from alembic import op
    op.drop_column("kpi_snapshots", "net_cash_position_try")
    op.drop_column("kpi_snapshots", "total_receivables_try")
    op.drop_column("kpi_snapshots", "projected_profit_try")
    op.drop_column("kpi_snapshots", "backlog_try")
