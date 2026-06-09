"""CR-003-I: variations table + RLS

Revision ID: 0006_cr003i_variations
Revises: 0005_fix_rls_no_force
Create Date: 2026-06-08
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_cr003i_variations"
down_revision = "0005_fix_rls_no_force"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    op.create_table(
        "variations",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("company_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("variation_number", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("submitted_date", sa.Date(), nullable=False),
        sa.Column("approved_date", sa.Date()),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("value_try", sa.Numeric(18, 2), nullable=False),
        sa.Column("approved_value_try", sa.Numeric(18, 2)),
        sa.Column("cost_impact_try", sa.Numeric(18, 2), server_default="0"),
        sa.Column("margin_impact_try", sa.Numeric(18, 2),
                  sa.Computed("COALESCE(approved_value_try, 0) - cost_impact_try", persisted=True)),
        sa.Column("cost_category", sa.String(50)),
        sa.Column("document_url", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean(), server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.execute("ALTER TABLE variations ENABLE ROW LEVEL SECURITY;")
    op.execute(f"CREATE POLICY variations_company_isolation ON variations FOR ALL USING (company_id = {CURRENT_COMPANY});")
    op.execute("CREATE POLICY variations_hide_deleted ON variations FOR SELECT USING (is_deleted = false);")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS variations_company_isolation ON variations;")
    op.execute("DROP POLICY IF EXISTS variations_hide_deleted ON variations;")
    op.drop_table("variations")
