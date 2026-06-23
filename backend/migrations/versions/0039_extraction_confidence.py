"""CR-024: persist AI document-extraction confidence

Adds a nullable ``extraction_confidence`` Float (0..1) to ``cost_entries`` and
``client_invoices``. The AI returns this 0–1 score at document capture / AI
import time; until now it was dropped. Purely additive nullable columns — NULL
for manually entered and standard-Excel rows (no AI involved). Display +
capture-quality monitoring only; never feeds the financial math.

Both tables are already company-scoped with RLS, so no new policy is needed.

Revision ID: 0039_extraction_confidence
Revises: 0038_cost_commitment_relief
Create Date: 2026-06-23
"""
import sqlalchemy as sa

from migrations.idempotent import add_column

revision = "0039_extraction_confidence"
down_revision = "0038_cost_commitment_relief"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # add_column is a no-op when the 0001 baseline already built the column.
    add_column("cost_entries", sa.Column("extraction_confidence", sa.Float(), nullable=True))
    add_column("client_invoices", sa.Column("extraction_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    from alembic import op

    op.drop_column("client_invoices", "extraction_confidence")
    op.drop_column("cost_entries", "extraction_confidence")
