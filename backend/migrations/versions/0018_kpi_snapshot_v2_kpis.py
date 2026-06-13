"""Add cost_to_complete and variations_net to kpi_snapshots (v2 dashboard KPIs)

Revision ID: 0018_kpi_snapshot_v2_kpis
Revises: 0017_project_revenue_model
Create Date: 2026-06-13
"""
import sqlalchemy as sa

from migrations.idempotent import add_column

revision = "0018_kpi_snapshot_v2_kpis"
down_revision = "0017_project_revenue_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column("kpi_snapshots", sa.Column("cost_to_complete_try", sa.Numeric(18, 2), nullable=False, server_default="0"))
    add_column("kpi_snapshots", sa.Column("variations_net_try", sa.Numeric(18, 2), nullable=False, server_default="0"))


def downgrade() -> None:
    from alembic import op

    op.drop_column("kpi_snapshots", "variations_net_try")
    op.drop_column("kpi_snapshots", "cost_to_complete_try")
