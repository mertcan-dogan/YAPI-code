"""CR-003-J: approval workflow columns

Revision ID: 0007_cr003j_approvals
Revises: 0006_cr003i_variations
Create Date: 2026-06-08
"""
import sqlalchemy as sa
from alembic import op

from migrations.idempotent import add_column

revision = "0007_cr003j_approvals"
down_revision = "0006_cr003i_variations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column("companies", sa.Column("approvals_enabled", sa.Boolean(), server_default="true"))
    add_column("companies", sa.Column("cost_approval_threshold_try", sa.Numeric(18, 2), server_default="500000"))
    add_column("companies", sa.Column("require_budget_approval", sa.Boolean(), server_default="false"))
    add_column("companies", sa.Column("require_subcontractor_approval", sa.Boolean(), server_default="false"))
    add_column("cost_entries", sa.Column("pending_approval", sa.Boolean(), server_default="false"))
    add_column("cost_entries", sa.Column("approval_reason", sa.Text()))


def downgrade() -> None:
    op.drop_column("cost_entries", "approval_reason")
    op.drop_column("cost_entries", "pending_approval")
    op.drop_column("companies", "require_subcontractor_approval")
    op.drop_column("companies", "require_budget_approval")
    op.drop_column("companies", "cost_approval_threshold_try")
    op.drop_column("companies", "approvals_enabled")
