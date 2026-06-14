"""Add document_sha256 to cost_entries (smart-capture duplicate detection)

Revision ID: 0019_cost_entry_doc_sha256
Revises: 0018_kpi_snapshot_v2_kpis
Create Date: 2026-06-14
"""
import sqlalchemy as sa

from migrations.idempotent import add_column

revision = "0019_cost_entry_doc_sha256"
down_revision = "0018_kpi_snapshot_v2_kpis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column("cost_entries", sa.Column("document_sha256", sa.String(64), nullable=True))


def downgrade() -> None:
    from alembic import op

    op.drop_column("cost_entries", "document_sha256")
