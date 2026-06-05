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


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
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
