"""CR-007 step 1: enable pg_trgm extension + ai_query_log audit table

Revision ID: 0021_pg_trgm_ai_query_log
Revises: 0020_ai_conversations
Create Date: 2026-06-15

NOTE: the revision id must stay <= 32 chars — alembic_version.version_num is
VARCHAR(32). The original id (0021_cr007_pg_trgm_and_ai_query_log, 35 chars)
overflowed it, so the version stamp failed and the whole migration rolled back
on prod boot (SQLite tests don't run migrations, so they never caught it).

Two pieces of groundwork for the AI Agent Core (CR-007), with no behaviour
change to existing features:

1. ``pg_trgm`` extension — vendor fuzzy-matching in get_vendor_spend /
   compare_vendors (CR-007-A §2.3, CR-007-D) uses trigram similarity() on
   PostgreSQL. The extension is Postgres-only; the SQLite test suite never runs
   this migration (it builds the schema from the ORM models via create_all) and
   falls back to normalised-equality + ILIKE.

2. ``ai_query_log`` table — append-only audit trail, one row per agent request
   (CR-007-E §6.1). Kept separate from ``audit_log`` (§0 B2): audit_log.action
   is String(10) and record_id is NOT nullable, so 'AI_AGENT_QUERY' over many
   records cannot live there. No soft-delete columns: purely append-only.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_index, create_policy, create_table, enable_rls

revision = "0021_pg_trgm_ai_query_log"
down_revision = "0020_ai_conversations"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    # 1. pg_trgm — Postgres only; harmless no-op elsewhere (the SQLite test DB
    #    never reaches this migration).
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # 2. ai_query_log — append-only, no soft-delete columns.
    create_table(
        "ai_query_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("tools_used", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("row_counts", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index(
        "ix_ai_query_log_company_created",
        "ai_query_log",
        ["company_id", "created_at"],
    )
    # Defense-in-depth RLS parity (the backend service role bypasses RLS; isolation
    # is also enforced in application code). Append-only: no UPDATE/DELETE.
    enable_rls("ai_query_log")
    create_policy(
        "ai_query_log_company_isolation",
        "ai_query_log",
        f"FOR ALL USING (company_id = {CURRENT_COMPANY})",
    )
    create_policy("ai_query_log_append_only_no_update", "ai_query_log", "FOR UPDATE USING (false)")
    create_policy("ai_query_log_append_only_no_delete", "ai_query_log", "FOR DELETE USING (false)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS ai_query_log_append_only_no_delete ON ai_query_log;")
    op.execute("DROP POLICY IF EXISTS ai_query_log_append_only_no_update ON ai_query_log;")
    op.execute("DROP POLICY IF EXISTS ai_query_log_company_isolation ON ai_query_log;")
    op.drop_index("ix_ai_query_log_company_created", table_name="ai_query_log")
    op.drop_table("ai_query_log")
    # pg_trgm is left installed on downgrade — other features may rely on it and
    # dropping a shared extension is destructive.
