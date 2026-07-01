"""CR-014-A: fx_rates global daily USD/TRY reference table

Revision ID: 0025_usd_tracking
Revises: 0024_equipment_photos
Create Date: 2026-06-16

A GLOBAL reference table (exchange rates are universal): no company_id, no
company RLS filter. ``rate_date`` is the primary key (one row per day). RLS is
enabled with a read-all SELECT policy; writes go through the backend service
role (which bypasses RLS), keeping it read-only to clients.

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32)).
"""
import sqlalchemy as sa

from migrations.idempotent import create_policy, create_table, enable_rls

revision = "0025_usd_tracking"
down_revision = "0024_equipment_photos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table(
        "fx_rates",
        sa.Column("rate_date", sa.Date(), primary_key=True, nullable=False),
        sa.Column("usd_try", sa.Numeric(10, 4), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="TCMB"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    enable_rls("fx_rates")
    # Global reference data — readable by everyone; only the service role writes.
    create_policy("fx_rates_read_all", "fx_rates", "FOR SELECT USING (true)")


def downgrade() -> None:
    from alembic import op

    op.execute("DROP POLICY IF EXISTS fx_rates_read_all ON fx_rates;")
    op.drop_table("fx_rates")
