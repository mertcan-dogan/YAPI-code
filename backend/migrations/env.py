"""Alembic migration environment for Yapı."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import settings
from app.db import _normalize_db_url
from app.models import Base  # registers all models on Base.metadata

# Railway/Heroku inject DATABASE_URL as a bare postgresql:// (no driver suffix),
# which SQLAlchemy resolves to the psycopg2 dialect — but we only ship psycopg 3.
# Normalize to postgresql+psycopg:// (same rule app/db.py applies) so that
# `alembic upgrade head` works in production instead of crashing on import.
DB_URL = _normalize_db_url(settings.database_url)

config = context.config
config.set_main_option("sqlalchemy.url", DB_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Build the engine directly from the already-normalized DB_URL rather than
    # going through engine_from_config + the alembic.ini section. This guarantees
    # the psycopg3 URL is what reaches create_engine — there is no raw
    # DATABASE_URL or ConfigParser interpolation step that could reintroduce the
    # psycopg2 dialect.
    connectable = create_engine(DB_URL, poolclass=pool.NullPool, future=True)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
