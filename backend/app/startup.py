"""Application startup tasks.

Running ``alembic upgrade head`` from the app's own startup (rather than only
from the Dockerfile CMD) makes schema migration **builder-agnostic**: it runs
whenever the process boots, regardless of whether the platform builds from the
Dockerfile, Nixpacks, or a custom start command. Without this, a deploy whose
start path doesn't include the migration step boots against a stale schema and
every query touching a new column 500s.

The upgrade is idempotent (see migrations/idempotent.py) and is run best-effort:
a failure is logged with a full traceback but never prevents the API from
serving, so a migration problem degrades to a diagnosable error instead of a
total outage.
"""
import logging
import sys
from pathlib import Path

from app.config import settings

logger = logging.getLogger("yapi.startup")

# backend/ — the directory containing alembic.ini and the migrations/ package.
_BACKEND_DIR = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    """Apply Alembic migrations up to head. Best-effort, never raises."""
    # Migrations target Postgres (RLS, JSONB, generated columns). Skip entirely
    # for non-Postgres URLs (e.g. the SQLite test database).
    if not settings.database_url.startswith(("postgres://", "postgresql")):
        logger.info("[startup] non-Postgres DATABASE_URL — skipping migrations")
        return

    # Ensure `from app...` and `from migrations...` resolve when env.py loads,
    # independent of the process working directory.
    if str(_BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(_BACKEND_DIR))

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))

    try:
        logger.info("[startup] running 'alembic upgrade head'…")
        command.upgrade(cfg, "head")
        logger.info("[startup] 'alembic upgrade head' complete — schema is up to date")
    except Exception:  # noqa: BLE001 — must not block the server from starting
        logger.exception(
            "[startup] 'alembic upgrade head' FAILED — starting the server anyway; "
            "the schema may be out of date until this is resolved"
        )
