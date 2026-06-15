"""CR-007-E — safety: rate limiting, degradation, ai_query_log (§6.1, §11.4)."""
from sqlalchemy import select

from app.config import settings
from app.constants import ROLE_DIRECTOR
from app.models.ai_query_log import AIQueryLog
from app.services import agent as agent_service
from app.services import ai as ai_service


# --- minimal fake Claude client -------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# ai_query_log
# --------------------------------------------------------------------------- #
def test_successful_agent_writes_one_query_log_row(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    uid = seed["a"]["users"][ROLE_DIRECTOR].id

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use", [_tool("list_projects", {})])
        return _Resp("end_turn", [_text("Portföyde projeler var.")])

    _patch(monkeypatch, responder)
    agent_service.run_agent(db, cid, [{"role": "user", "content": "Projeleri listele"}], user_id=uid)

    rows = db.execute(select(AIQueryLog).where(AIQueryLog.company_id == cid)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == uid
    assert row.question == "Projeleri listele"
    assert row.tools_used == ["list_projects"]
    assert row.row_counts == {"list_projects": 1}  # one seeded project


def test_query_log_records_no_record_contents(db, seed, monkeypatch):
    """Only question / tool names / row counts — never the rows themselves."""
    cid = seed["a"]["company"].id
    uid = seed["a"]["users"][ROLE_DIRECTOR].id
    _patch(monkeypatch, lambda call, kw: _Resp("end_turn", [_text("yok")]))
    agent_service.run_agent(db, cid, [{"role": "user", "content": "selam"}], user_id=uid)

    row = db.execute(select(AIQueryLog)).scalars().one()
    # The model has only id/company_id/user_id/question/tools_used/row_counts/created_at.
    cols = {c.name for c in AIQueryLog.__table__.columns}
    assert "records" not in cols and "data" not in cols


def test_no_log_when_user_id_absent(db, seed, monkeypatch):
    _patch(monkeypatch, lambda call, kw: _Resp("end_turn", [_text("x")]))
    agent_service.run_agent(db, seed["a"]["company"].id, [{"role": "user", "content": "x"}])
    assert db.execute(select(AIQueryLog)).scalars().all() == []


# --------------------------------------------------------------------------- #
# Degradation
# --------------------------------------------------------------------------- #
def test_run_agent_degrades_on_claude_error(db, seed, monkeypatch):
    def boom(call, kw):
        raise RuntimeError("connection reset")

    _patch(monkeypatch, boom)
    import pytest
    with pytest.raises(ai_service.AIUnavailable):
        agent_service.run_agent(db, seed["a"]["company"].id, [{"role": "user", "content": "x"}],
                                user_id=seed["a"]["users"][ROLE_DIRECTOR].id)
    # Failed request writes no log row.
    assert db.execute(select(AIQueryLog)).scalars().all() == []


def test_run_agent_degrades_on_timeout_budget(db, seed, monkeypatch):
    # Force the 60s budget to 0 so the first iteration trips it.
    monkeypatch.setattr(settings, "ai_agent_timeout_seconds", 0)
    _patch(monkeypatch, lambda call, kw: _Resp("end_turn", [_text("never reached")]))
    import pytest
    with pytest.raises(ai_service.AIUnavailable):
        agent_service.run_agent(db, seed["a"]["company"].id, [{"role": "user", "content": "x"}])


def test_endpoint_degrades_and_writes_no_log(client, seed, session_factory):
    # No API key configured -> _client raises -> endpoint returns degraded 200.
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/ai/agent", json={"messages": [{"role": "user", "content": "merhaba"}]})
    assert r.status_code == 200
    assert r.json()["data"]["answer_markdown"] == agent_service.DEGRADED_MESSAGE
    s = session_factory()
    try:
        assert s.execute(select(AIQueryLog)).scalars().all() == []
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# Rate limit (§11.4)
# --------------------------------------------------------------------------- #
def test_rate_limit_429_after_10_requests(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    body = {"messages": [{"role": "user", "content": "soru"}]}
    for _ in range(settings.ai_agent_rate_per_minute):  # 10 allowed
        r = client.post("/api/v1/ai/agent", json=body)
        assert r.status_code == 200, r.text
    r = client.post("/api/v1/ai/agent", json=body)  # 11th
    assert r.status_code == 429
    assert "Çok fazla istek" in r.json()["error"]["message"]


def test_config_defaults():
    assert settings.ai_agent_rate_per_minute == 10
    assert settings.ai_agent_timeout_seconds == 60
    assert settings.ai_agent_max_tokens == 2000
