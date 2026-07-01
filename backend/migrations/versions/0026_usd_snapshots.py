"""CR-014-B: per-row USD snapshot columns on costs & hakediş

Revision ID: 0026_usd_snapshots
Revises: 0025_usd_tracking
Create Date: 2026-06-16

Additive + nullable only — TRY columns are never touched, and the legacy
``project.usd_try_rate`` is left intact.
  - client_invoices.amount_usd   Numeric(18,2)  (cost_entries already has it)
  - cost_entries.fx_rate_usd     Numeric(10,4)  (snapshot rate applied)
  - client_invoices.fx_rate_usd  Numeric(10,4)  (snapshot rate applied)

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32)).
"""
import sqlalchemy as sa

from migrations.idempotent import add_column

revision = "0026_usd_snapshots"
down_revision = "0025_usd_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column("client_invoices", sa.Column("amount_usd", sa.Numeric(18, 2), nullable=True))
    add_column("cost_entries", sa.Column("fx_rate_usd", sa.Numeric(10, 4), nullable=True))
    add_column("client_invoices", sa.Column("fx_rate_usd", sa.Numeric(10, 4), nullable=True))


def downgrade() -> None:
    from alembic import op

    op.drop_column("client_invoices", "fx_rate_usd")
    op.drop_column("cost_entries", "fx_rate_usd")
    op.drop_column("client_invoices", "amount_usd")
