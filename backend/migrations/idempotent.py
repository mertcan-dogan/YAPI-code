"""Idempotent DDL helpers for migrations.

The 0001 baseline builds the *entire current* schema via
``Base.metadata.create_all`` (it reflects today's ORM models, not a frozen
snapshot). On a fresh database that means every later additive migration would
otherwise fail with "already exists". These helpers make each operation a no-op
when the object is already present, so ``alembic upgrade head`` converges any
database state — fresh, partially migrated, or fully built — to the model
schema without changing the end result.

CREATE POLICY has no IF NOT EXISTS, so policy creation is done drop-then-create
(the same idempotent pattern migration 0005 already uses).
"""
import sqlalchemy as sa
from alembic import op


def _inspector() -> sa.engine.reflection.Inspector:
    return sa.inspect(op.get_bind())


def has_table(table: str) -> bool:
    return _inspector().has_table(table)


def has_column(table: str, column: str) -> bool:
    insp = _inspector()
    if not insp.has_table(table):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def has_index(table: str, index: str) -> bool:
    insp = _inspector()
    if not insp.has_table(table):
        return False
    return index in {i["name"] for i in insp.get_indexes(table)}


def add_column(table: str, column: sa.Column) -> None:
    """op.add_column, skipped if the column already exists."""
    if not has_column(table, column.name):
        op.add_column(table, column)


def create_table(table: str, *columns, **kw) -> None:
    """op.create_table, skipped if the table already exists."""
    if not has_table(table):
        op.create_table(table, *columns, **kw)


def create_index(name: str, table: str, columns) -> None:
    """op.create_index, skipped if the table is missing or the index exists."""
    if has_table(table) and not has_index(table, name):
        op.create_index(name, table, columns)


def enable_rls(table: str) -> None:
    """ENABLE ROW LEVEL SECURITY (idempotent in Postgres) when the table exists."""
    if has_table(table):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")


def create_policy(name: str, table: str, body: str) -> None:
    """Create a policy idempotently (drop-then-create). ``body`` is everything
    after ``CREATE POLICY <name> ON <table>`` — e.g. ``"FOR ALL USING (...)"``."""
    if has_table(table):
        op.execute(f"DROP POLICY IF EXISTS {name} ON {table};")
        op.execute(f"CREATE POLICY {name} ON {table} {body};")
