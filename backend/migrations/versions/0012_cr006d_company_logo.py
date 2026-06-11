"""CR-006-D: companies.logo_url column for uploaded company logo

Revision ID: 0012_cr006d_company_logo
Revises: 0011_cr006c_notifications
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_cr006d_company_logo"
down_revision = "0011_cr006c_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Public Supabase Storage URL of the company logo (company-logos bucket).
    # Idempotent guard: the column may already exist on environments that picked
    # it up from the model before this migration was authored.
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("companies")]
    if "logo_url" not in cols:
        op.add_column("companies", sa.Column("logo_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "logo_url")
