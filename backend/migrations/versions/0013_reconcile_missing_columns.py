"""reconcile any model columns missing from the live database

Revision ID: 0013_reconcile_missing_columns
Revises: 0012_cr006d_company_logo
Create Date: 2026-06-11

Some model columns exist only because 0001's ``create_all`` reflects the current
models — they have no dedicated ALTER migration. A production database first
built from an older 0001 can therefore be missing them, and every query that
selects them 500s (e.g. /auth/me selecting users.last_login_at /
users.preferred_language, or reading companies.logo_url).

This migration walks ``Base.metadata`` and idempotently adds any column that is
absent from an existing table — closing all such drift in one pass, including:

    users.preferred_language   (VARCHAR, nullable, server default 'tr')
    users.last_login_at        (TIMESTAMPTZ, nullable)
    companies.logo_url         (TEXT, nullable)

It only ADDS columns (never drops/alters), and only ones that are safe to add to
a populated table (nullable or carrying a server default). It is fully
idempotent: on a database that already matches the models it is a no-op.
"""
import logging

import sqlalchemy as sa
from alembic import op

from app.models import Base
from migrations.idempotent import add_column, has_column, has_table

revision = "0013_reconcile_missing_columns"
down_revision = "0012_cr006d_company_logo"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    for table in Base.metadata.sorted_tables:
        # Whole-table creation is handled by earlier migrations (and 0001).
        if not has_table(table.name):
            continue

        for col in table.columns:
            if has_column(table.name, col.name):
                continue
            # Generated columns are computed by the DB; they can't be ADD COLUMN'd
            # the same way and would already exist if the table was created with
            # them. Primary keys are never missing from an existing table.
            if getattr(col, "computed", None) is not None or col.primary_key:
                continue
            # Only add columns that are safe on a populated table: a NOT NULL
            # column with no server default can't be back-filled here.
            if not col.nullable and col.server_default is None:
                logger.warning(
                    "0013: skipping %s.%s (NOT NULL without server default — "
                    "cannot safely add to a populated table)", table.name, col.name,
                )
                continue

            # Detached copy so the column isn't already bound to its Table.
            new_col = sa.Column(
                col.name,
                col.type,
                nullable=col.nullable,
                server_default=col.server_default,
            )
            logger.info("0013: adding missing column %s.%s", table.name, col.name)
            add_column(table.name, new_col)


def downgrade() -> None:
    # Reconciliation is additive and idempotent; there is no meaningful, safe
    # automatic downgrade (we can't know which columns this migration added).
    pass
