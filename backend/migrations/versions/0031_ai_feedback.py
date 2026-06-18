"""CR-024-A: ai_feedback (per-answer 👍/👎 trust feedback)

Revision ID: 0031_ai_feedback
Revises: 0030_project_milestones
Create Date: 2026-06-18

Additive only — no backfill, no change to any existing table. The new
``ai_feedback`` table records one row per user thumbs-up/down on an AI Agent
answer (CR-024). Append-only (no soft-delete), company-scoped + RLS, mirroring
``ai_query_log`` (CR-007): a single company-isolation policy and a composite
``(company_id, created_at)`` index.

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32) — the
CR-007 0021 trap). "0031_ai_feedback" is 16 chars.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_index, create_policy, create_table, enable_rls

revision = "0031_ai_feedback"
down_revision = "0030_project_milestones"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    create_table(
        "ai_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        # Nullable: a degraded answer (no ai_query_log row) can still be rated.
        sa.Column("ai_query_log_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_query_log.id"), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("rating", sa.String(8), nullable=False),  # "up" | "down"
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # Composite index on (company_id, created_at) — CR-024 §0.0.3.
    create_index("ix_ai_feedback_company_created", "ai_feedback", ["company_id", "created_at"])

    # RLS company-isolation (defence in depth), mirroring ai_query_log.
    enable_rls("ai_feedback")
    create_policy(
        "ai_feedback_company_isolation", "ai_feedback",
        f"FOR ALL USING (company_id = {CURRENT_COMPANY})",
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS ai_feedback_company_isolation ON ai_feedback;")
    op.drop_index("ix_ai_feedback_company_created", table_name="ai_feedback")
    op.drop_table("ai_feedback")
