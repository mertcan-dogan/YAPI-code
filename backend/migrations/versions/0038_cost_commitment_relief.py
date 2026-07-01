"""CR-023: commitment relief link + light PO metadata on cost_entries

Adds:
- ``commitment_id`` — nullable self-FK (an *actual* entry points to the
  committed entry it fulfils; open_commitment nets these out so a commitment and
  its invoice never double-count exposure).
- ``po_number`` / ``expected_date`` — optional PO metadata on committed entries.

cost_entries is already company-scoped with RLS, so no new policy is needed —
these are purely additive nullable columns. An index on commitment_id keeps the
relief lookup cheap.

Revision ID: 0038_cost_commitment_relief
Revises: 0037_automations
Create Date: 2026-06-22
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.idempotent import add_column, create_index

revision = "0038_cost_commitment_relief"
down_revision = "0037_automations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Self-FK declared inline so the column carries the constraint on Postgres;
    # add_column is a no-op when the 0001 baseline already built it.
    add_column(
        "cost_entries",
        sa.Column(
            "commitment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cost_entries.id"),
            nullable=True,
        ),
    )
    add_column("cost_entries", sa.Column("po_number", sa.String(100), nullable=True))
    add_column("cost_entries", sa.Column("expected_date", sa.Date(), nullable=True))
    create_index("ix_cost_entries_commitment_id", "cost_entries", ["commitment_id"])


def downgrade() -> None:
    from alembic import op

    op.drop_index("ix_cost_entries_commitment_id", table_name="cost_entries")
    op.drop_column("cost_entries", "expected_date")
    op.drop_column("cost_entries", "po_number")
    op.drop_column("cost_entries", "commitment_id")
