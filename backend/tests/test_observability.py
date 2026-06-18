"""Tests for the observability layer (CR-OBS).

Covers the two go-live guarantees:
  * Sentry is env-gated and never leaks PII / financial data.
  * The migration-head integrity check correctly detects a stale schema.

No real Sentry client is ever initialized here — ``sentry_sdk.init`` is mocked so
the global SDK state stays clean across the rest of the suite.
"""
import logging

import pytest

from app.services import observability as obs


# --------------------------------------------------------------------------- #
# Sentry: env-gating (no DSN => complete no-op)
# --------------------------------------------------------------------------- #


def test_init_sentry_is_noop_without_dsn(monkeypatch):
    monkeypatch.setattr(obs, "_sentry_enabled", False)
    assert obs.init_sentry("") is False
    assert obs.init_sentry(None) is False
    assert obs.sentry_enabled() is False


def test_app_starts_and_sentry_disabled_in_tests(client):
    # The app imported and the TestClient is serving — proving init_sentry ran as a
    # no-op at import (no SENTRY_DSN in the test env) without crashing the app.
    assert obs.sentry_enabled() is False
    assert client.get("/health").status_code == 200


def test_init_sentry_with_dsn_uses_secure_settings(monkeypatch):
    """A DSN initializes the SDK with errors-only + PII-off settings."""
    import sentry_sdk

    captured = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: captured.update(kw))
    monkeypatch.setattr(obs, "_sentry_enabled", False)

    assert obs.init_sentry("https://key@o0.ingest.sentry.io/1", "production") is True
    assert obs.sentry_enabled() is True

    # Security-critical configuration (KVKK + financial data).
    assert captured["send_default_pii"] is False
    assert captured["traces_sample_rate"] == 0.0
    assert captured["profiles_sample_rate"] == 0.0
    assert captured["max_request_body_size"] == "never"
    assert captured["include_local_variables"] is False
    assert captured["before_send"] is obs._before_send
    assert captured["environment"] == "production"


# --------------------------------------------------------------------------- #
# Sentry: before_send scrubbing (never send PII / financial data)
# --------------------------------------------------------------------------- #


def test_before_send_strips_body_and_sensitive_fields():
    event = {
        "request": {
            "data": {"amount_try": 50000, "vendor_name": "Gizli Tedarik A.Ş."},
            "cookies": {"session": "abc"},
            "query_string": "token=secret123",
            "env": {"REMOTE_ADDR": "1.2.3.4"},
            "headers": {"Authorization": "Bearer xyz", "Content-Type": "application/json"},
        },
        "user": {"email": "a@b.com", "ip_address": "1.2.3.4"},
        "extra": {"email": "leak@x.com", "note": "ok", "amount": 999},
        # diagnostic data that MUST survive scrubbing
        "exception": {"values": [{"stacktrace": {"frames": [{"filename": "/app/x.py", "function": "f"}]}}]},
    }

    out = obs._before_send(event, {})
    req = out["request"]

    # Request body / cookies / query / wsgi-env are gone entirely.
    assert "data" not in req
    assert "cookies" not in req
    assert "query_string" not in req
    assert "env" not in req
    # Credential header masked, benign header kept.
    assert req["headers"]["Authorization"] == "[redacted]"
    assert req["headers"]["Content-Type"] == "application/json"
    # No user identification.
    assert "user" not in out
    # Sensitive keys in custom context redacted, benign key kept.
    assert out["extra"]["email"] == "[redacted]"
    assert out["extra"]["amount"] == "[redacted]"
    assert out["extra"]["note"] == "ok"
    # Stack trace preserved (exact-match redaction must not clobber "filename").
    assert out["exception"]["values"][0]["stacktrace"]["frames"][0]["filename"] == "/app/x.py"


def test_redact_uses_exact_key_match_not_substring():
    # "filename" contains "name" but must NOT be redacted.
    assert obs._redact({"filename": "/x.py"}) == {"filename": "/x.py"}
    assert obs._redact({"name": "Ahmet"}) == {"name": "[redacted]"}


# --------------------------------------------------------------------------- #
# Migration integrity: pure comparison helper
# --------------------------------------------------------------------------- #


def test_migration_head_matches_true_when_equal():
    assert obs.migration_head_matches("0030", "0030") is True


def test_migration_head_matches_false_on_mismatch():
    assert obs.migration_head_matches("0029", "0030") is False


def test_migration_head_matches_false_when_unknown():
    # Fail-closed: a missing current/expected is treated as a mismatch.
    assert obs.migration_head_matches(None, "0030") is False
    assert obs.migration_head_matches("0030", None) is False
    assert obs.migration_head_matches(None, None) is False


# --------------------------------------------------------------------------- #
# Migration integrity: check_migration_head with mocked Alembic state
# --------------------------------------------------------------------------- #


def test_check_migration_head_ok_when_revisions_match(monkeypatch):
    monkeypatch.setattr(obs, "get_expected_head", lambda: "0030")
    monkeypatch.setattr(obs, "get_current_revision", lambda conn: "0030")
    status = obs.check_migration_head(connection=object())
    assert status.ok is True
    assert status.current == "0030"
    assert status.expected == "0030"


def test_check_migration_head_detects_mismatch(monkeypatch):
    monkeypatch.setattr(obs, "get_expected_head", lambda: "0030")
    monkeypatch.setattr(obs, "get_current_revision", lambda conn: "0028")
    status = obs.check_migration_head(connection=object())
    assert status.ok is False
    assert status.current == "0028"
    assert status.expected == "0030"


# --------------------------------------------------------------------------- #
# Boot-time check: logs ERROR + alerts Sentry only on mismatch
# --------------------------------------------------------------------------- #


def test_verify_on_boot_logs_and_alerts_on_mismatch(monkeypatch, caplog):
    import sentry_sdk

    monkeypatch.setattr(obs, "get_expected_head", lambda: "0030")
    monkeypatch.setattr(obs, "get_current_revision", lambda conn: "0028")
    monkeypatch.setattr(obs, "_sentry_enabled", True)

    alerts = []
    monkeypatch.setattr(sentry_sdk, "capture_message", lambda msg, level=None: alerts.append((msg, level)))

    with caplog.at_level(logging.ERROR, logger="yapi.observability"):
        status = obs.verify_migration_head_on_boot(connection=object())

    assert status.ok is False
    assert any("mismatch" in r.message.lower() for r in caplog.records)
    assert len(alerts) == 1
    assert alerts[0][1] == "error"
    assert "0028" in alerts[0][0] and "0030" in alerts[0][0]


def test_verify_on_boot_is_quiet_when_ok(monkeypatch, caplog):
    import sentry_sdk

    monkeypatch.setattr(obs, "get_expected_head", lambda: "0030")
    monkeypatch.setattr(obs, "get_current_revision", lambda conn: "0030")
    monkeypatch.setattr(obs, "_sentry_enabled", True)

    alerts = []
    monkeypatch.setattr(sentry_sdk, "capture_message", lambda msg, level=None: alerts.append((msg, level)))

    with caplog.at_level(logging.ERROR, logger="yapi.observability"):
        status = obs.verify_migration_head_on_boot(connection=object())

    assert status.ok is True
    assert alerts == []
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_verify_on_boot_does_not_alert_when_sentry_disabled(monkeypatch):
    monkeypatch.setattr(obs, "get_expected_head", lambda: "0030")
    monkeypatch.setattr(obs, "get_current_revision", lambda conn: "0028")
    monkeypatch.setattr(obs, "_sentry_enabled", False)

    import sentry_sdk

    def _boom(*a, **k):  # would raise if called
        raise AssertionError("capture_message must not be called when Sentry is disabled")

    monkeypatch.setattr(sentry_sdk, "capture_message", _boom)
    # Should simply log and return without touching Sentry.
    assert obs.verify_migration_head_on_boot(connection=object()).ok is False


# --------------------------------------------------------------------------- #
# /health surfaces the migration fields
# --------------------------------------------------------------------------- #


def test_health_includes_migration_fields(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body) >= {"status", "db_migration_ok", "db_revision", "expected_revision"}
    assert isinstance(body["db_migration_ok"], bool)
    # The latest script head is always resolvable from the migrations package.
    assert body["expected_revision"] is not None
