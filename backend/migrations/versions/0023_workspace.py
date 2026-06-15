"""CR-008-A: workspace_items table (per-user pinned snapshots)

Revision ID: 0023_workspace
Revises: 0022_vendors
Create Date: 2026-06-15

Per-user "Çalışma Alanım" board, mirroring the ai_conversations pattern:
company-scoped, per-user, soft-deleted, client-generated id. Each item is a
SNAPSHOT (frozen AgentChartSpec or {answer_markdown, citations}). ``layout``
holds the {x, y, w, h} grid cell, persisted by the reorder endpoint (CR-008-B).

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32)).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_index, create_policy, create_table, enable_rls

revision = "0023_workspace"
down_revision = "0022_vendors"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    create_table(
        "workspace_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("item_type", sa.String(20), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source_conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("layout", postgresql.JSONB(), nullable=True),
        sa.Column("pinned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index("ix_workspace_items_user", "workspace_items", ["user_id", "is_deleted"])

    enable_rls("workspace_items")
    create_policy("workspace_items_company_isolation", "workspace_items",
                  f"FOR ALL USING (company_id = {CURRENT_COMPANY})")
    create_policy("workspace_items_hide_deleted", "workspace_items",
                  "FOR SELECT USING (is_deleted = false)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS workspace_items_hide_deleted ON workspace_items;")
    op.execute("DROP POLICY IF EXISTS workspace_items_company_isolation ON workspace_items;")
    op.drop_index("ix_workspace_items_user", table_name="workspace_items")
    op.drop_table("workspace_items")
