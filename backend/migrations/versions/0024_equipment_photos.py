"""Add photo_urls to equipment_log (equipment detail photo gallery)

Revision ID: 0024_equipment_photos
Revises: 0023_workspace
Create Date: 2026-06-16

Additive, nullable-free with a default of an empty JSON array, so existing rows
get ``[]`` and the column never holds NULL. Holds public Supabase Storage URLs
for uploaded equipment photos.

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32)).
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.idempotent import add_column

revision = "0024_equipment_photos"
down_revision = "0023_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column(
        "equipment_log",
        sa.Column("photo_urls", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    from alembic import op

    op.drop_column("equipment_log", "photo_urls")
