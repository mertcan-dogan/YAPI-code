"""CR-011 follow-up (Item 2) — explicit action requests fire the propose_ tools.

The agent was answering action requests in free text. We strengthened the
tool-use steering and added a server-resolved relative due-date for reminders.
The model is mocked here, so these tests verify the WIRING that a correct tool
call relies on: the steering text is present + directive, the due-date is
resolved on the server, and a fired propose_ tool yields a PENDING approval
request + a proposed_actions entry with ZERO direct mutations (invariant intact).
"""
from datetime import date, timedelta

from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR
from app.models.ai_alert import AIAlert
from app.models.approval_request import ApprovalRequest
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.notification import Notification
from app.services import agent as agent_service
from app.services import ai as ai_service

BUSINESS_MODELS = [Notification, AIAlert, CostEntry, ClientInvoice]


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


def _ids(seed):
    return seed["a"]["company"].id, seed["a"]["users"][ROLE_DIRECTOR].id


def _counts(db):
    return {m.__name__: db.execute(select(func.count()).select_from(m)).scalar() for m in BUSINESS_MODELS}


# --------------------------------------------------------------------------- #
# Steering text is present + directive
# --------------------------------------------------------------------------- #
def test_action_guidance_is_directive():
    g = agent_service._ACTION_GUIDANCE
    assert "MUTLAKA" in g                       # forces the tool call
    assert "propose_reminder" in g
    assert "propose_flag_invoice" in g
    assert "propose_followup_task" in g
    assert "hatırlat" in g                       # reminder trigger phrase
    assert "işaretle" in g                       # flag trigger phrase
    assert "GENEL TAVSİYE" in g                   # advice → free text, no tool


def test_system_prompt_includes_action_guidance(db, seed, monkeypatch):
    cid, _ = _ids(seed)
    captured = {}
    monkeypatch.setattr(ai_service, "_client", lambda: _Client(
        lambda call, kw: captured.update(kw) or _Resp("end_turn", [_Block(type="text", text="ok")])))
    agent_service.run_agent(db, cid, [{"role": "user", "content": "x"}])
    assert "MUTLAKA" in captured["system"]


# --------------------------------------------------------------------------- #
# Server-resolved relative due-date
# --------------------------------------------------------------------------- #
def test_resolve_due_named():
    today = date(2026, 6, 20)
    assert agent_service.resolve_due("bugun", today) == today
    assert agent_service.resolve_due("yarin", today) == today + timedelta(days=1)
    assert agent_service.resolve_due("gelecek_hafta", today) == today + timedelta(days=7)
    assert agent_service.resolve_due("iki_hafta", today) == today + timedelta(days=14)
    assert agent_service.resolve_due("ay_sonu", today) == date(2026, 6, 30)
    assert agent_service.resolve_due("gelecek_ay", today) == date(2026, 7, 20)
    assert agent_service.resolve_due("bilinmeyen", today) is None


def test_due_param_in_reminder_schema():
    schema = next(t for t in agent_service.build_tool_schemas() if t["name"] == "propose_reminder")
    props = schema["input_schema"]["properties"]
    assert "due" in props and props["due"]["enum"] == list(agent_service.RELATIVE_DUE)


# --------------------------------------------------------------------------- #
# Action-intent flow: fired propose_reminder → pending request, server due, 0 writes
# --------------------------------------------------------------------------- #
def test_action_intent_fires_propose_with_server_resolved_due(db, seed, monkeypatch):
    cid, uid = _ids(seed)
    today = date(2026, 6, 20)
    before = _counts(db)

    def responder(call, kw):
        if call == 0:
            # A correct model, seeing the steering, calls the tool with a named due.
            return _Resp("tool_use", [_Block(type="tool_use", name="propose_reminder",
                                             input={"title": "Hakedişi kontrol et", "due": "yarin"}, id="a0")])
        return _Resp("end_turn", [_Block(type="text", text="Öneri oluşturuldu, onayınızı bekliyor.")])

    _patch(monkeypatch, responder)
    out = agent_service.run_agent(
        db, cid, [{"role": "user", "content": "bana yarın hakedişi kontrol etmeyi hatırlat"}],
        user_id=uid, today=today,
    )

    assert out["tools_used"] == ["propose_reminder"]
    assert len(out["proposed_actions"]) == 1
    assert out["proposed_actions"][0]["kind"] == "agent_reminder"

    req = db.execute(
        select(ApprovalRequest).where(ApprovalRequest.kind == "agent_reminder")
    ).scalars().one()
    assert req.status == "pending" and req.proposed_by_agent
    # Due-date resolved on the server (today + 1), not by the model.
    assert req.payload["due_date"] == "2026-06-21"
    # Invariant: zero direct mutations to business tables.
    assert _counts(db) == before


def test_explicit_due_date_wins_over_named(db, seed, monkeypatch):
    cid, uid = _ids(seed)

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use", [_Block(type="tool_use", name="propose_reminder",
                                             input={"title": "X", "due": "yarin",
                                                    "due_date": "2026-12-31"}, id="a0")])
        return _Resp("end_turn", [_Block(type="text", text="ok")])

    _patch(monkeypatch, responder)
    agent_service.run_agent(db, cid, [{"role": "user", "content": "hatırlat"}],
                            user_id=uid, today=date(2026, 6, 20))
    req = db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_reminder")).scalars().one()
    assert req.payload["due_date"] == "2026-12-31"
