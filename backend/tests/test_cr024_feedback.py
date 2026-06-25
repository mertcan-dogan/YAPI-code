"""CR-024-D — AI feedback endpoints + additive agent-response fields.

Mirrors the ai_query_log test style (fake Claude client) for the service-level
guard test, and exercises the new POST/GET /ai/agent/feedback endpoints over the
SQLite-backed TestClient.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.constants import ROLE_DIRECTOR, ROLE_FINANCE, ROLE_PROJECT_MANAGER
from app.models.ai_feedback import AIFeedback
from app.models.ai_query_log import AIQueryLog
from app.services import agent as agent_service
from app.services import ai as ai_service


# --- minimal fake Claude client (same shape as test_cr007e_safety) ---------- #
class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _Messages:
    def __init__(self, responder):
        self._r = responder
        self.calls = 0

    def create(self, **kw):
        r = self._r(self.calls, kw)
        self.calls += 1
        return r


class _Client:
    def __init__(self, responder):
        self.messages = _Messages(responder)


def _patch(monkeypatch, responder):
    monkeypatch.setattr(ai_service, "_client", lambda: _Client(responder))


def _tool(name, inp, id="t0"):
    return _Block(type="tool_use", name=name, input=inp, id=id)


def _text(t):
    return _Block(type="text", text=t)


FB_URL = "/api/v1/ai/agent/feedback"


# --------------------------------------------------------------------------- #
# POST /ai/agent/feedback
# --------------------------------------------------------------------------- #
def test_feedback_up_stored_company_scoped(client, seed, session_factory):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post(FB_URL, json={"question": "Marj neden düştü?", "rating": "up"})
    assert r.status_code == 200, r.text
    fid = r.json()["data"]["id"]

    s = session_factory()
    try:
        row = s.get(AIFeedback, __import__("uuid").UUID(fid))
        assert row is not None
        assert row.company_id == seed["a"]["company"].id
        assert row.user_id == seed["a"]["users"][ROLE_DIRECTOR].id
        assert row.rating == "up"
        assert row.comment is None
        assert row.question == "Marj neden düştü?"
    finally:
        s.close()


def test_feedback_down_with_comment_stored(client, seed, session_factory):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post(FB_URL, json={"question": "S", "rating": "down", "comment": "Yanlış tedarikçi"})
    assert r.status_code == 200, r.text
    s = session_factory()
    try:
        row = s.execute(select(AIFeedback)).scalars().one()
        assert row.rating == "down"
        assert row.comment == "Yanlış tedarikçi"
    finally:
        s.close()


def test_feedback_invalid_rating_422(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post(FB_URL, json={"question": "S", "rating": "meh"})
    assert r.status_code == 422
    assert r.json()["success"] is False


def test_feedback_overlong_comment_422(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post(FB_URL, json={"question": "S", "rating": "down", "comment": "x" * 2001})
    assert r.status_code == 422


def test_feedback_empty_question_422(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post(FB_URL, json={"question": "   ", "rating": "up"})
    assert r.status_code == 422


def test_feedback_links_only_same_company_query_log(client, seed, db, session_factory):
    """A query_log_id from another company must NOT be linked (stored as null),
    and must never 404 — the feedback is still recorded."""
    # A log row in company B.
    b_log = AIQueryLog(
        company_id=seed["b"]["company"].id, user_id=seed["b"]["users"][ROLE_DIRECTOR].id,
        question="x", tools_used=[], row_counts={},
    )
    db.add(b_log)
    db.commit()
    b_log_id = str(b_log.id)

    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post(FB_URL, json={"question": "S", "rating": "up", "query_log_id": b_log_id})
    assert r.status_code == 200, r.text
    s = session_factory()
    try:
        row = s.execute(select(AIFeedback)).scalars().one()
        assert row.ai_query_log_id is None  # cross-company link refused
    finally:
        s.close()


def test_feedback_links_own_company_query_log(client, seed, db, session_factory):
    a_log = AIQueryLog(
        company_id=seed["a"]["company"].id, user_id=seed["a"]["users"][ROLE_DIRECTOR].id,
        question="x", tools_used=[], row_counts={},
    )
    db.add(a_log)
    db.commit()
    a_log_id = str(a_log.id)

    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post(FB_URL, json={"question": "S", "rating": "up", "query_log_id": a_log_id})
    assert r.status_code == 200, r.text
    s = session_factory()
    try:
        row = s.execute(select(AIFeedback)).scalars().one()
        assert str(row.ai_query_log_id) == a_log_id
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# GET /ai/agent/feedback (directors only)
# --------------------------------------------------------------------------- #
def _seed_feedback(db, seed, label, n, base):
    for i in range(n):
        db.add(AIFeedback(
            company_id=seed[label]["company"].id,
            user_id=seed[label]["users"][ROLE_DIRECTOR].id,
            question=f"{label}-{i}", rating="up",
            created_at=base + timedelta(minutes=i),
        ))
    db.commit()


def test_get_feedback_company_scoped_newest_first(client, seed, db):
    base = datetime(2026, 6, 18, 9, 0, tzinfo=timezone.utc)
    _seed_feedback(db, seed, "a", 3, base)
    _seed_feedback(db, seed, "b", 2, base)

    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get(FB_URL)
    assert r.status_code == 200, r.text
    body = r.json()
    data = body["data"]
    assert body["meta"]["total"] == 3  # only company A
    assert all(row["question"].startswith("a-") for row in data)
    # newest first: a-2 (latest) before a-0
    assert data[0]["question"] == "a-2"
    assert data[-1]["question"] == "a-0"
    assert data[0]["user"] == seed["a"]["users"][ROLE_DIRECTOR].full_name


def test_get_feedback_non_director_blocked(client, seed):
    for role in (ROLE_FINANCE, ROLE_PROJECT_MANAGER):
        client.login(seed["a"]["users"][role])
        r = client.get(FB_URL)
        assert r.status_code == 403, f"{role} should be blocked"


def test_get_feedback_requires_auth(client, seed):
    r = client.get(FB_URL)
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# /ai/agent additive response fields + _log_query return value
# --------------------------------------------------------------------------- #
def test_agent_response_has_query_log_id_and_row_counts_and_no_other_changes(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    uid = seed["a"]["users"][ROLE_DIRECTOR].id

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use", [_tool("list_projects", {})])
        return _Resp("end_turn", [_text("Portföy özeti.")])

    _patch(monkeypatch, responder)
    out = agent_service.run_agent(db, cid, [{"role": "user", "content": "Projeleri listele"}], user_id=uid)

    # Additive keys present and real.
    assert out["row_counts"] == {"list_projects": 1}
    assert isinstance(out["query_log_id"], str) and out["query_log_id"]
    # All previously-existing keys still present and unchanged in shape
    # (CR-011-C adds the additive `proposed_actions` list).
    assert set(out.keys()) == {
        "answer_markdown", "charts", "citations", "tools_used",
        "generated_at", "notes", "query_log_id", "row_counts", "proposed_actions",
        # CR-011 rich steps (additive): per-tool aggregate summaries + token usage.
        "tool_summaries", "usage",
    }
    assert out["proposed_actions"] == []  # read-only answer -> no proposals
    assert out["answer_markdown"] == "Portföy özeti."
    assert out["tools_used"] == ["list_projects"]
    # query_log_id points at the real logged row.
    row = db.execute(select(AIQueryLog).where(AIQueryLog.company_id == cid)).scalars().one()
    assert out["query_log_id"] == str(row.id)


def test_degraded_response_has_consistent_shape():
    out = agent_service.degraded_response()
    assert out["query_log_id"] is None
    assert out["row_counts"] == {}
    assert out["proposed_actions"] == []
    assert set(out.keys()) == {
        "answer_markdown", "charts", "citations", "tools_used",
        "generated_at", "notes", "query_log_id", "row_counts", "proposed_actions",
        # CR-011 rich steps (additive): per-tool aggregate summaries + token usage.
        "tool_summaries", "usage",
    }


def test_log_query_returns_id_on_success(db, seed):
    cid = seed["a"]["company"].id
    uid = seed["a"]["users"][ROLE_DIRECTOR].id
    rid = agent_service._log_query(db, cid, uid, [{"role": "user", "content": "soru"}], ["list_projects"], {"list_projects": 1})
    assert rid is not None
    assert db.get(AIQueryLog, rid) is not None


def test_log_query_returns_none_on_failure(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    uid = seed["a"]["users"][ROLE_DIRECTOR].id

    def boom():
        raise RuntimeError("db write failed")

    monkeypatch.setattr(db, "commit", boom)
    # Must swallow the error and return None (never break the response).
    rid = agent_service._log_query(db, cid, uid, [{"role": "user", "content": "x"}], [], {})
    assert rid is None
