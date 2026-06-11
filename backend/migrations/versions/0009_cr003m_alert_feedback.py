"""CR-003-M: ai_alerts.feedback

Revision ID: 0009_cr003m_alert_feedback
Revises: 0008_cr003l_budget_templates
Create Date: 2026-06-08
"""
import sqlalchemy as sa
from alembic import op

from migrations.idempotent import add_column

revision = "0009_cr003m_alert_feedback"
down_revision = "0008_cr003l_budget_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column("ai_alerts", sa.Column("feedback", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_alerts", "feedback")
