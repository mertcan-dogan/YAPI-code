"""Database engine and session management (SQLAlchemy 2.0).

The engine is created lazily so that importing the app does not require the
database driver to be installed (useful for tooling and unit tests that never
touch the DB). Tests may inject their own SessionLocal via set_sessionmaker().
"""
from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None
_admin_engine: Engine | None = None
_AdminSessionLocal: sessionmaker | None = None


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


def _build_engine(db_url: str) -> Engine:
    db_url = _normalize_db_url(db_url)
    connect_args: dict = {}
    if db_url.startswith("postgresql+psycopg://"):
        # pgbouncer (transaction mode) can't preserve server-side prepared
        # statements across pooled backends; disable psycopg 3 auto-prepare.
        connect_args["prepare_threshold"] = None
    return create_engine(
        db_url, pool_pre_ping=True, future=True, connect_args=connect_args
    )


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine(settings.database_url)
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
    """FastAPI dependency yielding a DB session.

    Under the CR-040 rollout this is the NOBYPASSRLS app role's session; it is
    scoped to the caller's company by get_current_user via set_session_company.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- CR-040: escalated (RLS-bypassing) session -------------------------------
# For paths that legitimately need cross-company or pre-auth DB access and so
# must NOT be tenant-scoped: the auth user lookup (must read users before the
# company is known), the cron scheduler (runs across all companies), and the
# login-stamp write. Backed by ADMIN_DATABASE_URL (service_role/owner). When that
# is blank it reuses the normal sessionmaker, so single-URL deploys and the
# SQLite test suite (which also override get_sessionmaker) are unaffected.

def get_admin_sessionmaker() -> sessionmaker:
    global _admin_engine, _AdminSessionLocal
    if not settings.admin_database_url:
        return get_sessionmaker()
    if _AdminSessionLocal is None:
        _admin_engine = _build_engine(settings.admin_database_url)
        _AdminSessionLocal = sessionmaker(
            bind=_admin_engine, autocommit=False, autoflush=False, future=True
        )
    return _AdminSessionLocal


def AdminSessionLocal() -> Session:
    return get_admin_sessionmaker()()


def get_admin_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding an escalated (RLS-bypassing) DB session."""
    db = AdminSessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- CR-040: per-request tenant scoping via the app.current_company GUC -------
# RLS policies (migration 0040) filter every company-scoped table on
# current_setting('app.current_company'). We carry the request's company on the
# Session's .info and (re)apply it transaction-locally. The after_begin listener
# re-applies at the start of EVERY transaction on the session, so a router that
# commits mid-request (opening a fresh transaction) stays scoped, and a pooled
# connection never inherits a previous request's scope (is_local resets at commit).
#
# Contract: company_id is a real uuid string or absent — NEVER ''. An unset GUC
# yields NULL in the policy (NULLIF(...,'')::uuid) → zero rows (fail-closed).

def set_session_company(session: Session, company_id) -> None:
    """Bind a request's company to its DB session for RLS scoping."""
    cid = str(company_id) if company_id else None
    session.info["company_id"] = cid
    # If a transaction is already open, after_begin won't fire again until the
    # next begin — apply now so the in-flight transaction is scoped too.
    if cid and session.in_transaction():
        bind = session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT set_config('app.current_company', :cid, true)"),
                {"cid": cid},
            )


@event.listens_for(Session, "after_begin")
def _apply_company_guc(session: Session, transaction, connection) -> None:
    # GUC/RLS is Postgres-only; the SQLite test database no-ops here.
    if connection.dialect.name != "postgresql":
        return
    cid = session.info.get("company_id")
    if cid:
        connection.execute(
            text("SELECT set_config('app.current_company', :cid, true)"),
            {"cid": str(cid)},
        )
