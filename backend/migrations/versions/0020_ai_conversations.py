"""ai_conversations table — per-user AI Asistan chat history (cross-device sync)

Revision ID: 0020_ai_conversations
Revises: 0019_cost_entry_doc_sha256
Create Date: 2026-06-15
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_index, create_policy, create_table, enable_rls

revision = "0020_ai_conversations"
down_revision = "0019_cost_entry_doc_sha256"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    create_table(
        "ai_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("messages", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index(
        "ix_ai_conversations_user_updated",
        "ai_conversations",
        ["user_id", "is_deleted", "updated_at"],
    )
    # Defense-in-depth RLS parity (the backend service role bypasses RLS via NO
    # FORCE; isolation is also enforced in application code).
    enable_rls("ai_conversations")
    create_policy(
        "ai_conversations_company_isolation",
        "ai_conversations",
        f"FOR ALL USING (company_id = {CURRENT_COMPANY})",
    )
    create_policy(
        "ai_conversations_hide_deleted",
        "ai_conversations",
        "FOR SELECT USING (is_deleted = false)",
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS ai_conversations_hide_deleted ON ai_conversations;")
    op.execute("DROP POLICY IF EXISTS ai_conversations_company_isolation ON ai_conversations;")
    op.drop_index("ix_ai_conversations_user_updated", table_name="ai_conversations")
    op.drop_table("ai_conversations")
