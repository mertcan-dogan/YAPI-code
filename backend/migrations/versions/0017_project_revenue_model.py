"""Project revenue model + sales-based fields (kat karşılığı / yap-sat)

Revision ID: 0017_project_revenue_model
Revises: 0016_user_dashboard_layout
Create Date: 2026-06-13
"""
import sqlalchemy as sa

from migrations.idempotent import add_column

revision = "0017_project_revenue_model"
down_revision = "0016_user_dashboard_layout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column("projects", sa.Column("revenue_model", sa.String(30), nullable=False, server_default="hakedis"))
    add_column("projects", sa.Column("contractor_share_pct", sa.Numeric(5, 2), nullable=True))
    add_column("projects", sa.Column("unit_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    from alembic import op
    op.drop_column("projects", "unit_count")
    op.drop_column("projects", "contractor_share_pct")
    op.drop_column("projects", "revenue_model")
