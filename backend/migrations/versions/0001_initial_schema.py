"""initial schema — all core tables (Section 2.3)

Revision ID: 0001_initial_schema
Revises:
Create Date: 2025-06-05

Creates every table directly from the SQLAlchemy metadata so the database
matches the ORM models exactly. Requires the pgcrypto extension for
gen_random_uuid().
"""
from alembic import op

from app.models import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
