"""CR-003-L: custom_budget_templates table + RLS

Revision ID: 0008_cr003l_budget_templates
Revises: 0007_cr003j_approvals
Create Date: 2026-06-08
"""
import sqlalchemy as sa
from alembic import op

from migrations.idempotent import create_policy, create_table, enable_rls

revision = "0008_cr003l_budget_templates"
down_revision = "0007_cr003j_approvals"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    create_table(
        "custom_budget_templates",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("distribution", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), server_default="false"),
    )
    enable_rls("custom_budget_templates")
    create_policy("custom_budget_templates_company_isolation", "custom_budget_templates",
                  f"FOR ALL USING (company_id = {CURRENT_COMPANY})")
    create_policy("custom_budget_templates_hide_deleted", "custom_budget_templates",
                  "FOR SELECT USING (is_deleted = false)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS custom_budget_templates_company_isolation ON custom_budget_templates;")
    op.execute("DROP POLICY IF EXISTS custom_budget_templates_hide_deleted ON custom_budget_templates;")
    op.drop_table("custom_budget_templates")
