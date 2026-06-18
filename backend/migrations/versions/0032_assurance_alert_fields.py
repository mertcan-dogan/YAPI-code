"""CR-022-A: assurance record-linkage fields on ai_alerts

Revision ID: 0032_assurance_alert_fields
Revises: 0031_ai_feedback
Create Date: 2026-06-18

Additive only — three nullable columns on the existing ``ai_alerts`` table so an
alert can point at the offending record and carry a stable per-issue dedup key
(CR-022 anomaly findings). Existing alerts keep NULLs → zero behavior change.
Reuses ai_alerts' existing RLS (no policy change). Composite index on
``(company_id, dedup_key)`` for the dedup lookup.

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32) — the
CR-007 0021 trap). "0032_assurance_alert_fields" is 27 chars.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import add_column, create_index

revision = "0032_assurance_alert_fields"
down_revision = "0031_ai_feedback"
branch_labels = None
depends_on = None

TABLE = "ai_alerts"


def upgrade() -> None:
    add_column(TABLE, sa.Column("source_type", sa.String(length=30), nullable=True))
    add_column(TABLE, sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True))
    add_column(TABLE, sa.Column("dedup_key", sa.String(length=200), nullable=True))
    create_index("ix_ai_alerts_company_dedup", TABLE, ["company_id", "dedup_key"])


def downgrade() -> None:
    op.drop_index("ix_ai_alerts_company_dedup", table_name=TABLE)
    op.drop_column(TABLE, "dedup_key")
    op.drop_column(TABLE, "source_id")
    op.drop_column(TABLE, "source_type")
