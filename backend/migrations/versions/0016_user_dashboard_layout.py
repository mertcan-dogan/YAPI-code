"""Per-user dashboard layout (customizable Ana Sayfa)

Revision ID: 0016_user_dashboard_layout
Revises: 0015_kpi_snapshot_exec_metrics
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.idempotent import add_column

revision = "0016_user_dashboard_layout"
down_revision = "0015_kpi_snapshot_exec_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column("users", sa.Column("dashboard_layout", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    from alembic import op
    op.drop_column("users", "dashboard_layout")
