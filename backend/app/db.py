"""Database engine and session management (SQLAlchemy 2.0).

The engine is created lazily so that importing the app does not require the
database driver to be installed (useful for tooling and unit tests that never
touch the DB). Tests may inject their own SessionLocal via set_sessionmaker().
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _normalize_db_url(db_url: str) -> str:
    """Force the psycopg 3 driver for any Postgres URL.

    We ship psycopg 3 only (no psycopg2). A DATABASE_URL can arrive in several
    shapes that SQLAlchemy would otherwise resolve to the psycopg2 dialect:

    * ``postgres://…`` / ``postgresql://…`` — bare, as Railway/Heroku inject it
      (no driver suffix defaults to psycopg2).
    * ``postgresql+psycopg2://…`` — an explicit psycopg2 driver, e.g. left over
      in a platform env var from an earlier psycopg2 deployment.

    All of these are rewritten to ``postgresql+psycopg://`` so psycopg 3 is
    always used. URLs that already specify ``+psycopg`` are left untouched, as
    are non-Postgres URLs (e.g. ``sqlite://`` in tests).
    """
    for prefix in (
        "postgresql+psycopg2://",
        "postgres+psycopg2://",
        "postgresql://",
        "postgres://",
    ):
        if db_url.startswith(prefix):
            db_url = "postgresql+psycopg://" + db_url[len(prefix):]
            break

    # Strip connection params that some platforms append for Supabase's pooler
    # but psycopg 3 / libpq reject (e.g. ``pgbouncer=true`` -> ``invalid
    # connection option "pgbouncer"``, which aborts every connect — including
    # ``alembic upgrade head`` on boot — and surfaces as a 500 on DB routes).
    # Done by surgical string edit so every other param is preserved verbatim.
    if db_url.startswith("postgresql+psycopg://") and "?" in db_url:
        base, _, query = db_url.partition("?")
        kept = [
            kv for kv in query.split("&")
            if kv and kv.split("=", 1)[0].lower() != "pgbouncer"
        ]
        db_url = base + ("?" + "&".join(kept) if kept else "")
    return db_url


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        db_url = _normalize_db_url(settings.database_url)
        connect_args: dict = {}
        if db_url.startswith("postgresql+psycopg://"):
            # pgbouncer (transaction mode) can't preserve server-side prepared
            # statements across pooled backends; disable psycopg 3 auto-prepare.
            connect_args["prepare_threshold"] = None
        _engine = create_engine(
            db_url, pool_pre_ping=True, future=True, connect_args=connect_args
        )
    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False, future=True)
    return _SessionLocal


def set_sessionmaker(maker: sessionmaker) -> None:
    """Override the session factory (used by the test suite)."""
    global _SessionLocal
    _SessionLocal = maker


def SessionLocal() -> Session:
    return get_sessionmaker()()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
