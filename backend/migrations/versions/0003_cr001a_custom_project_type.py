"""CR-001-A: projects.custom_project_type

Revision ID: 0003_cr001a_custom_project_type
Revises: 0002_enable_rls
Create Date: 2025-06-07
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_cr001a_custom_project_type"
down_revision = "0002_enable_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("custom_project_type", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "custom_project_type")
