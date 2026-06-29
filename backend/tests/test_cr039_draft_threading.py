"""CR-039 — conversational authoring.

propose_report / propose_dashboard are DRAFT tools: they validate the spec exactly
as before but write NOTHING (no ApprovalRequest, no Report/Dashboard row, no
request_id) and return a draft_* proposed-action carrying the validated spec. The
active draft threads back via the request ``draft`` field and lands in the agent
system context so the model edits the real spec. Creation is the user's OLUŞTUR
click — never the agent.
"""
from datetime import date

import pytest
from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR
from app.models.approval_request import ApprovalRequest
from app.models.dashboard import Dashboard
from app.models.report import Report
from app.services import agent as agent_service
from app.services import agent_actions as actions


def _ids(seed, label="a"):
    return (seed[label]["company"].id,
            seed[label]["users"][ROLE_DIRECTOR].id,
            seed[label]["project"].id)


def _counts(db):
    return (
        db.execute(select(func.count()).select_from(ApprovalRequest)).scalar(),
        db.execute(select(func.count()).select_from(Report)).scalar(),
        db.execute(select(func.count()).select_from(Dashboard)).scalar(),
    )


REPORT_SPEC = {"metrics": ["cost_try"], "dimensions": ["project"], "viz": "table"}
DASH_WIDGETS = [{"id": "w1", "type": "kpi", "title": "Maliyet",
                 "layout": {"x": 0, "y": 0, "w": 3, "h": 2},
                 "spec": {"metrics": ["cost_try"], "viz": "kpi"}}]


# --------------------------------------------------------------------------- #
# Draft tools: validate, return the spec, write NOTHING
# --------------------------------------------------------------------------- #
def test_propose_report_returns_draft_without_writing(db, seed):
    cid, uid, _ = _ids(seed)
    before = _counts(db)
    out = actions.propose_report(db, cid, uid, title="Proje Kârlılığı", spec=REPORT_SPEC)
    assert out["status"] == "draft"
    pa = out["proposed_action"]
    assert pa["kind"] == "draft_report"
    assert pa["title"] == "Proje Kârlılığı"
    assert pa["spec"] == REPORT_SPEC
    assert pa["visibility"] == "private"
    assert "request_id" not in pa  # a draft has no approval request
    assert _counts(db) == before  # no ApprovalRequest, no Report row


def test_propose_dashboard_returns_draft_without_writing(db, seed):
    cid, uid, _ = _ids(seed)
    before = _counts(db)
    out = actions.propose_dashboard(db, cid, uid, title="Özet Pano", widgets=DASH_WIDGETS)
    assert out["status"] == "draft"
    pa = out["proposed_action"]
    assert pa["kind"] == "draft_dashboard"
    assert pa["widgets"] and pa["widgets"][0]["id"] == "w1"
    assert "request_id" not in pa
    assert _counts(db) == before


def test_propose_report_invalid_spec_raises_no_draft(db, seed):
    cid, uid, _ = _ids(seed)
    before = _counts(db)
    with pytest.raises(actions.ActionError):
        actions.propose_report(db, cid, uid, title="Bozuk",
                               spec={"metrics": ["__not_a_metric__"]})
    assert _counts(db) == before  # invalid → no draft, no write


def test_propose_report_requires_title(db, seed):
    cid, uid, _ = _ids(seed)
    with pytest.raises(actions.ActionError):
        actions.propose_report(db, cid, uid, title="  ", spec=REPORT_SPEC)


# --------------------------------------------------------------------------- #
# Refine context: the draft round-trips into the agent system prompt
# --------------------------------------------------------------------------- #
def test_draft_context_round_trips_into_system_prompt():
    draft = {"kind": "draft_report", "title": "Kârlılık", "spec": REPORT_SPEC}
    ctx = agent_service._draft_context(draft)
    assert "Kârlılık" in ctx and "cost_try" in ctx and "güncelle" in ctx.lower()
    system = agent_service._build_system(date(2026, 6, 19), None, draft_context=ctx)
    assert "TASLAK BAĞLAMI" in system and "Kârlılık" in system


def test_draft_context_dashboard_and_malformed():
    d = agent_service._draft_context(
        {"kind": "draft_dashboard", "title": "Pano", "widgets": DASH_WIDGETS}
    )
    assert "Pano" in d and "1 widget" in d
    # Malformed / absent → "" (never raises, never breaks the turn).
    assert agent_service._draft_context(None) == ""
    assert agent_service._draft_context({"kind": "draft_report"}) == ""
    assert agent_service._draft_context({"kind": "other"}) == ""


# --------------------------------------------------------------------------- #
# Endpoint forwards the draft to the agent
# --------------------------------------------------------------------------- #
def test_agent_endpoint_forwards_draft(client, seed, monkeypatch):
    captured = {}

    def fake_run_agent(db, company_id, messages, **kw):
        captured.update(kw)
        return {
            "answer_markdown": "ok", "charts": [], "citations": [], "tools_used": [],
            "generated_at": "2026-06-19T08:00:00Z", "notes": None, "query_log_id": None,
            "row_counts": {}, "proposed_actions": [], "tool_summaries": {}, "usage": None,
        }

    from app.services import agent as agent_mod
    monkeypatch.setattr(agent_mod, "run_agent", fake_run_agent)
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    draft = {"kind": "draft_report", "title": "X", "spec": REPORT_SPEC}
    r = client.post(
        "/api/v1/ai/agent",
        json={"messages": [{"role": "user", "content": "aylık yap"}], "draft": draft},
    )
    assert r.status_code == 200, r.text
    assert captured.get("draft") == draft
