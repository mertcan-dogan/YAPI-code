"""Observability: error monitoring (Sentry) + a boot-time migration integrity check.

Two independent concerns live here, both deliberately env-gated so local dev and
the test suite behave exactly as before:

1. Sentry — errors only. We do NOT enable Tracing/Profiling (sample rates 0.0) to
   preserve the free event quota for real errors, and we NEVER send PII or
   financial payloads: ``send_default_pii=False``, request bodies are dropped, no
   local variables are captured, and a ``before_send`` hook redacts obviously
   sensitive fields as defense-in-depth (KVKK + financial-data constraint).

2. Migration integrity — compare the Alembic revision applied in the DB against
   the latest script head. A silent mismatch (a stamp/rollback that went
   unnoticed) is the exact failure mode this guards against. The comparison is a
   small, pure helper so it can be unit-tested with mocks.

If ``SENTRY_DSN`` is unset, Sentry is completely disabled — ``sentry_sdk`` is not
even imported, nothing is initialized, and no warnings are emitted.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("yapi.observability")

# backend/ — holds alembic.ini and the migrations/ package.
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# Tracks whether init_sentry() actually initialized the SDK this process. Used so
# callers can decide whether to capture_message without importing sentry_sdk
# themselves (and so this stays correct even if sentry_sdk isn't installed).
_sentry_enabled = False


# --------------------------------------------------------------------------- #
# Sentry — PII/financial scrubbing
# --------------------------------------------------------------------------- #

# Exact (lowercased) key names we redact wherever they appear in scrubbed
# sub-trees. Exact-match — NOT substring — so we never clobber diagnostic keys
# like ``filename`` (which contains "name") and destroy a stack trace.
_SENSITIVE_KEYS = frozenset(
    {
        # monetary
        "amount", "amount_try", "amount_usd", "tutar", "tutar_try", "tutar_usd",
        "contract_value", "contract_value_try", "original_budget_try", "budget",
        "salary", "maas", "maaş", "price", "fiyat", "total", "toplam",
        # people / vendors (person + company names, contacts)
        "vendor", "vendor_name", "tedarikci", "tedarikçi", "client_name",
        "name", "full_name", "fullname", "isim", "ad", "soyad", "person",
        "email", "e_mail", "mail", "eposta", "e_posta", "phone", "telefon",
        "iban", "tckn", "tc_kimlik", "address", "adres",
        # secrets / auth
        "token", "access_token", "refresh_token", "id_token", "jwt",
        "secret", "jwt_secret", "password", "sifre", "şifre", "parola",
        "authorization", "cookie", "api_key", "apikey", "anthropic_api_key",
        "encryption_key", "service_key", "anon_key", "dsn",
    }
)

# Request headers carrying credentials — masked rather than dropped so the event
# still shows that a header was present.
_SENSITIVE_HEADERS = frozenset(
    {"authorization", "cookie", "set-cookie", "x-api-key", "proxy-authorization"}
)

_REDACTED = "[redacted]"


def _redact(value):
    """Recursively copy ``value``, replacing values under sensitive keys.

    Operates on plain dict/list structures only; scalars pass through. Applied to
    user-controlled sub-trees of the event (extra, request, breadcrumbs) — never
    to the exception/stacktrace, so diagnostics stay intact.
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS:
                out[k] = _REDACTED
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def _before_send(event, hint):
    """Strip request bodies and redact sensitive fields before an event leaves.

    Defense-in-depth on top of ``send_default_pii=False`` /
    ``max_request_body_size="never"`` / ``include_local_variables=False``. Returns
    the mutated event (or None to drop it — we never drop here).
    """
    try:
        req = event.get("request")
        if isinstance(req, dict):
            # Never transmit the request body, cookies, query string, or WSGI env
            # (carries REMOTE_ADDR + raw headers) — these can hold amounts, names,
            # tokens, etc.
            for k in ("data", "cookies", "query_string", "env"):
                req.pop(k, None)
            headers = req.get("headers")
            if isinstance(headers, dict):
                for h in list(headers):
                    if isinstance(h, str) and h.lower() in _SENSITIVE_HEADERS:
                        headers[h] = _REDACTED
            event["request"] = _redact(req)

        # No user identification (email / ip / username).
        event.pop("user", None)

        # Custom context we may attach + auto-captured breadcrumbs.
        if isinstance(event.get("extra"), dict):
            event["extra"] = _redact(event["extra"])
        if isinstance(event.get("breadcrumbs"), dict):
            # sentry stores breadcrumbs as {"values": [...]}
            event["breadcrumbs"] = _redact(event["breadcrumbs"])
        elif isinstance(event.get("breadcrumbs"), list):
            event["breadcrumbs"] = _redact(event["breadcrumbs"])
    except Exception:  # pragma: no cover - scrubbing must never break delivery
        logger.warning("[observability] before_send scrub failed", exc_info=True)
    return event


def init_sentry(dsn: str, environment: str = "development", release: str | None = None) -> bool:
    """Initialize Sentry for errors only. No-op (returns False) when ``dsn`` is empty.

    Errors-only: traces/profiles sample rates are 0.0 so the free quota is spent
    on real errors. No PII or financial data is sent (see module docstring).
    """
    global _sentry_enabled
    if not dsn:
        _sentry_enabled = False
        return False

    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=environment or "development",
        release=release,
        # Errors only — Tracing/Profiling deliberately disabled (free-quota).
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        # Hard security constraint (KVKK + financial data): send less.
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        before_send=_before_send,
    )
    _sentry_enabled = True
    logger.info("[observability] Sentry initialized (environment=%s, errors-only)", environment)
    return True


def sentry_enabled() -> bool:
    """True iff init_sentry() initialized the SDK this process."""
    return _sentry_enabled


# --------------------------------------------------------------------------- #
# Migration integrity check
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MigrationStatus:
    """Result of comparing the applied DB revision to the latest script head."""

    ok: bool
    current: str | None
    expected: str | None


def migration_head_matches(current: str | None, expected: str | None) -> bool:
    """Pure comparison: True only when a revision is applied AND equals the head.

    A ``None`` current (no ``alembic_version`` row / unreadable) or a ``None``
    expected (couldn't resolve the script head) is treated as a mismatch — fail
    closed, because "we don't know" is exactly the silent state we're guarding
    against.
    """
    return current is not None and expected is not None and current == expected


def get_expected_head() -> str | None:
    """Latest Alembic script head from ``migrations/versions`` (None on error)."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:  # noqa: BLE001 - never let a diagnostics helper raise
        logger.warning("[observability] could not resolve Alembic script head", exc_info=True)
        return None


def get_current_revision(connection) -> str | None:
    """Currently applied Alembic revision for ``connection`` (None if unknown).

    Returns None when there is no ``alembic_version`` table (e.g. the SQLite test
    DB) or the read fails, rather than raising — callers treat None as a mismatch.
    """
    try:
        from alembic.runtime.migration import MigrationContext

        return MigrationContext.configure(connection).get_current_revision()
    except Exception:  # noqa: BLE001
        logger.warning("[observability] could not read current DB revision", exc_info=True)
        return None


def check_migration_head(connection) -> MigrationStatus:
    """Compare the applied revision on ``connection`` to the latest script head."""
    expected = get_expected_head()
    current = get_current_revision(connection)
    return MigrationStatus(
        ok=migration_head_matches(current, expected),
        current=current,
        expected=expected,
    )


def verify_migration_head_on_boot(connection) -> MigrationStatus:
    """Boot-time check: log an ERROR (and alert Sentry) on a head mismatch.

    This is the silent-failure protection — an unnoticed migration stamp/rollback
    surfaces here as a logged error and a Sentry event, instead of as broken
    queries later. Never raises; returns the status for the caller/tests.
    """
    status = check_migration_head(connection)
    if status.ok:
        logger.info("[observability] DB migration head OK (revision %s)", status.current)
        return status

    msg = (
        "DB migration head mismatch — the applied schema revision does not match "
        f"the latest migration. current={status.current!r} expected={status.expected!r}"
    )
    logger.error("[observability] %s", msg)
    if sentry_enabled():
        try:
            import sentry_sdk

            sentry_sdk.capture_message(msg, level="error")
        except Exception:  # pragma: no cover
            logger.warning("[observability] failed to send Sentry alert for migration mismatch", exc_info=True)
    return status
