"""CR-015-A: financing-cost settings (company defaults + project overrides)

Revision ID: 0029_financing_settings
Revises: 0028_cost_subcategories
Create Date: 2026-06-16

Additive only. ``companies`` gains financing_enabled (default FALSE — opt-in),
financing_annual_rate_pct (nullable USD annual rate), financing_basis (default
"cumulative"); ``projects`` gains nullable financing_enabled_override /
financing_annual_rate_pct_override (NULL = inherit the company default).
Financing defaults OFF, so there is zero behavior change until enabled. No backfill.

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32) — the
CR-007 0021 trap).
"""
import sqlalchemy as sa

from migrations.idempotent import add_column

revision = "0029_financing_settings"
down_revision = "0028_cost_subcategories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column("companies", sa.Column("financing_enabled", sa.Boolean(), server_default="false", nullable=False))
    add_column("companies", sa.Column("financing_annual_rate_pct", sa.Numeric(5, 2), nullable=True))
    add_column("companies", sa.Column("financing_basis", sa.String(12), server_default="cumulative", nullable=False))
    add_column("projects", sa.Column("financing_enabled_override", sa.Boolean(), nullable=True))
    add_column("projects", sa.Column("financing_annual_rate_pct_override", sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    from alembic import op

    op.drop_column("projects", "financing_annual_rate_pct_override")
    op.drop_column("projects", "financing_enabled_override")
    op.drop_column("companies", "financing_basis")
    op.drop_column("companies", "financing_annual_rate_pct")
    op.drop_column("companies", "financing_enabled")
