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
            return "postgresql+psycopg://" + db_url[len(prefix):]
    return db_url


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        db_url = _normalize_db_url(settings.database_url)
        _engine = create_engine(db_url, pool_pre_ping=True, future=True)
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
