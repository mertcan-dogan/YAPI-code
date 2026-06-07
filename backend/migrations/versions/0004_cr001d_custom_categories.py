"""CR-001-D: custom_cost_categories table + RLS

Revision ID: 0004_cr001d_custom_categories
Revises: 0003_cr001a_custom_project_type
Create Date: 2025-06-07
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_cr001d_custom_categories"
down_revision = "0003_cr001a_custom_project_type"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    op.create_table(
        "custom_cost_categories",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_normalized", sa.String(length=255), nullable=False),
        sa.Column("usage_count", sa.Integer(), server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), server_default="false"),
        sa.UniqueConstraint("company_id", "name_normalized", name="uq_custom_cat_company_name"),
    )
    # RLS: company isolation (Section 2.4 pattern).
    op.execute("ALTER TABLE custom_cost_categories ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE custom_cost_categories FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY custom_cost_categories_company_isolation ON custom_cost_categories
        FOR ALL USING (company_id = {CURRENT_COMPANY});
        """
    )
    op.execute(
        """
        CREATE POLICY custom_cost_categories_hide_deleted ON custom_cost_categories
        FOR SELECT USING (is_deleted = false);
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS custom_cost_categories_company_isolation ON custom_cost_categories;")
    op.execute("DROP POLICY IF EXISTS custom_cost_categories_hide_deleted ON custom_cost_categories;")
    op.drop_table("custom_cost_categories")
