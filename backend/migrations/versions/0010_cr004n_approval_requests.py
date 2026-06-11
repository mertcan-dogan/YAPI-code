"""CR-004-N: generic approval requests + extra trigger toggles

Revision ID: 0010_cr004n_approval_requests
Revises: 0009_cr003m_alert_feedback
Create Date: 2026-06-10
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import add_column, create_index, create_table

revision = "0010_cr004n_approval_requests"
down_revision = "0009_cr003m_alert_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New per-trigger toggles (default On per CR-004-N). Existing companies also
    # get the budget/subcontractor toggles flipped on to enforce the workflow.
    add_column("companies", sa.Column("require_deletion_approval", sa.Boolean(), server_default="true"))
    add_column("companies", sa.Column("require_variation_approval", sa.Boolean(), server_default="true"))
    op.execute("UPDATE companies SET require_budget_approval = true, require_subcontractor_approval = true")

    create_table(
        "approval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("target_table", sa.String(50), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount_try", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index("ix_approval_requests_company_status", "approval_requests", ["company_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_approval_requests_company_status", table_name="approval_requests")
    op.drop_table("approval_requests")
    op.drop_column("companies", "require_variation_approval")
    op.drop_column("companies", "require_deletion_approval")
