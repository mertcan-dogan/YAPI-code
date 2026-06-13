"""CR-006-C: in-app notifications table

Revision ID: 0011_cr006c_notifications
Revises: 0010_cr004n_approval_requests
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_index, create_table

revision = "0011_cr006c_notifications"
down_revision = "0010_cr004n_approval_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        # user_id NULL => visible to all company users.
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        # overdue_payment | margin_warning | budget_overrun | invoice_received | ai_alert
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), server_default="medium", nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("related_project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index(
        "ix_notifications_company_read",
        "notifications",
        ["company_id", "is_read", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_company_read", table_name="notifications")
    op.drop_table("notifications")
