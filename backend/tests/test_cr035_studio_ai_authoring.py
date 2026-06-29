"""CR-035 + CR-039 — Report Studio AI authoring + "Bu rapor hakkında sor".

THE invariant (CR-011, non-negotiable): the agent NEVER writes a report/dashboard
directly. CR-039 STRENGTHENS this — propose_report / propose_dashboard are now
DRAFT tools: they validate the spec but write NOTHING (no ApprovalRequest, no
report/dashboard row, no request_id) and return a draft_* proposed-action carrying
the spec. The user creates their OWN report/pano via OLUŞTUR (POST /studio/...).
The legacy agent_create_report/dashboard ApprovalRequest appliers stay DORMANT —
still functional for any in-flight pending row, but never produced by the agent
anymore. These tests assert the draft behavior, spec validity, that the dormant
applier still applies an in-flight request correctly (company-scoped, owner from
the request row), and that "Bu rapor hakkında sor" grounding is read-only.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR
from app.models.approval_request import ApprovalRequest
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.dashboard import Dashboard
from app.models.report import Report
from app.services import agent as agent_service
from app.services import agent_actions as actions
from app.services import ai as ai_service
from app.services import approvals as approvals_service
from app.services.studio import creators
from app.services.studio.engine import run_spec

SPEC_TABLE = {"metrics": ["cost_try"], "dimensions": ["project"], "viz": "table"}
SPEC_KPI = {"metrics": ["cost_try"], "viz": "kpi"}
WIDGETS = [
    {"id": "w1", "type": "kpi", "title": "Maliyet",
     "layout": {"x": 0, "y": 0, "w": 3, "h": 2}, "spec": SPEC_KPI},
]


def _ids(seed, label="a"):
    return (seed[label]["company"].id,
            seed[label]["users"][ROLE_DIRECTOR].id,
            seed[label]["project"].id)


def _counts(db):
    return {
        "reports": db.execute(select(func.count()).select_from(Report)).scalar(),
        "dashboards": db.execute(select(func.count()).select_from(Dashboard)).scalar(),
        "costs": db.execute(select(func.count()).select_from(CostEntry)).scalar(),
        "invoices": db.execute(select(func.count()).select_from(ClientInvoice)).scalar(),
    }


def _pending(db, cid, kind):
    return db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.company_id == cid,
            ApprovalRequest.status == "pending",
            ApprovalRequest.kind == kind,
        )
    ).scalars().all()


# --------------------------------------------------------------------------- #
# 1. THE invariant — propose writes NOTHING but a pending request
# --------------------------------------------------------------------------- #
def test_propose_report_zero_mutation(db, seed):
    cid, uid, _ = _ids(seed)
    before = _counts(db)
    r = actions.propose_report(db, cid, uid, title="Daire Tipi Kârlılık", spec=SPEC_TABLE)

    # CR-039 — a DRAFT: validated, but NO ApprovalRequest and NO request_id.
    assert r["status"] == "draft"
    assert r["proposed_action"]["kind"] == "draft_report"
    # FE live-preview enrichment: the spec rides along on the proposed_action.
    assert r["proposed_action"]["spec"] == SPEC_TABLE
    assert r["proposed_action"]["title"] == "Daire Tipi Kârlılık"
    assert "request_id" not in r["proposed_action"]
    # The agent wrote NOTHING — no report row AND no pending approval request.
    assert _counts(db) == before
    assert _pending(db, cid, "agent_create_report") == []


def test_propose_dashboard_zero_mutation(db, seed):
    cid, uid, _ = _ids(seed)
    before = _counts(db)
    r = actions.propose_dashboard(db, cid, uid, title="Özet Pano", widgets=WIDGETS)

    assert r["status"] == "draft"
    assert r["proposed_action"]["kind"] == "draft_dashboard"
    assert r["proposed_action"]["widgets"][0]["spec"] == SPEC_KPI
    assert "request_id" not in r["proposed_action"]
    assert _counts(db) == before
    assert _pending(db, cid, "agent_create_dashboard") == []


# --------------------------------------------------------------------------- #
# 2. Spec validity — an out-of-catalog id is rejected, NO request created
# --------------------------------------------------------------------------- #
def test_propose_report_rejects_unknown_metric_no_request(db, seed):
    cid, uid, _ = _ids(seed)
    with pytest.raises(actions.ActionError):
        actions.propose_report(db, cid, uid, title="Kötü",
                               spec={"metrics": ["nonexistent_metric"]})
    assert _pending(db, cid, "agent_create_report") == []
    assert _counts(db)["reports"] == 0


def test_propose_report_rejects_empty_metrics(db, seed):
    cid, uid, _ = _ids(seed)
    with pytest.raises(actions.ActionError):
        actions.propose_report(db, cid, uid, title="Kötü", spec={"metrics": []})
    assert _pending(db, cid, "agent_create_report") == []


def test_propose_dashboard_rejects_bad_widget_spec_no_request(db, seed):
    cid, uid, _ = _ids(seed)
    bad = [{"id": "w1", "type": "kpi", "title": "t", "layout": {"x": 0, "y": 0, "w": 1, "h": 1},
            "spec": {"metrics": ["nope"]}}]
    with pytest.raises(actions.ActionError):
        actions.propose_dashboard(db, cid, uid, title="Kötü", widgets=bad)
    assert _pending(db, cid, "agent_create_dashboard") == []
    assert _counts(db)["dashboards"] == 0


def test_propose_report_requires_title(db, seed):
    cid, uid, _ = _ids(seed)
    with pytest.raises(actions.ActionError):
        actions.propose_report(db, cid, uid, title="   ", spec=SPEC_TABLE)


def test_invalid_spec_through_agent_loop_is_recoverable(db, seed, monkeypatch):
    """An out-of-catalog spec must surface as a RECOVERABLE tool error inside the
    agent loop (the model can correct), NOT a 500 — and create nothing."""
    cid, uid, _ = _ids(seed)

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use", [_Block(type="tool_use", name="propose_report",
                         input={"title": "X", "spec": {"metrics": ["nope_metric"]}}, id="t0")])
        return _Resp("end_turn", [_Block(type="text", text="Spec geçersizdi, düzeltmem gerek.")])

    monkeypatch.setattr(ai_service, "_client", lambda: _Client(responder))
    out = agent_service.run_agent(db, cid, [{"role": "user", "content": "rapor yap"}], user_id=uid)

    # The loop recovered (no exception) and still produced an answer.
    assert out["answer_markdown"]
    assert "propose_report" in out["tools_used"]
    # The invalid spec created neither a pending request nor a report.
    assert _pending(db, cid, "agent_create_report") == []
    assert _counts(db)["reports"] == 0


def test_dashboard_widget_cap_rejected_no_request(db, seed):
    cid, uid, _ = _ids(seed)
    too_many = [
        {"id": f"w{i}", "type": "kpi", "title": f"K{i}",
         "layout": {"x": 0, "y": i, "w": 3, "h": 2}, "spec": dict(SPEC_KPI)}
        for i in range(creators.MAX_DASHBOARD_WIDGETS + 1)
    ]
    with pytest.raises(actions.ActionError):
        actions.propose_dashboard(db, cid, uid, title="Çok büyük", widgets=too_many)
    assert _pending(db, cid, "agent_create_dashboard") == []


# --------------------------------------------------------------------------- #
# 3. The DORMANT agent_create_* applier still applies an in-flight request.
#    (CR-039: the agent no longer PRODUCES these requests, but the appliers are
#    kept so any pending row from before CR-039 still resolves correctly.)
# --------------------------------------------------------------------------- #
def _inflight_report_request(db, cid, uid):
    req = approvals_service.create_request(
        db, company_id=cid, project_id=None, kind="agent_create_report",
        target_table="reports", target_id=None,
        payload={"title": "Kârlılık", "spec": SPEC_TABLE, "visibility": "private", "labels": None},
        description="Rapor önerisi: Kârlılık", requested_by=uid, proposed_by_agent=True,
    )
    db.commit()
    return req


def test_dormant_applier_creates_report_from_inflight_request(db, seed):
    cid, uid, _ = _ids(seed)
    req = _inflight_report_request(db, cid, uid)
    assert _counts(db)["reports"] == 0

    created = approvals_service.apply_request(db, req)
    approvals_service.mark_decided(req, user_id=uid, status="approved")
    db.commit()

    assert created["table"] == "reports"
    report = db.get(Report, uuid.UUID(created["id"]))
    assert report is not None
    assert report.company_id == cid          # company-scoped (from the request row)
    assert report.owner_id == uid            # owned by the requester
    assert report.created_by == uid
    assert report.spec == SPEC_TABLE
    assert report.visibility == "private"
    # It runs identically to a hand-built report.
    result = run_spec(db, cid, report.spec)
    assert "rows" in result and "totals" in result


def test_dormant_applier_creates_dashboard_from_inflight_request(db, seed):
    cid, uid, _ = _ids(seed)
    normalised = creators.validate_widgets(db, cid, uid, WIDGETS)
    widgets_json = [w.model_dump(mode="json") for w in normalised]
    req = approvals_service.create_request(
        db, company_id=cid, project_id=None, kind="agent_create_dashboard",
        target_table="dashboards", target_id=None,
        payload={"title": "Pano", "widgets": widgets_json, "date_range": None,
                 "comparison": None, "filters": None, "visibility": "private", "labels": None},
        description="Pano önerisi: Pano", requested_by=uid, proposed_by_agent=True,
    )
    db.commit()
    assert _counts(db)["dashboards"] == 0

    created = approvals_service.apply_request(db, req)
    approvals_service.mark_decided(req, user_id=uid, status="approved")
    db.commit()

    assert created["table"] == "dashboards"
    dash = db.get(Dashboard, uuid.UUID(created["id"]))
    assert dash is not None
    assert dash.company_id == cid and dash.owner_id == uid
    assert dash.widgets[0]["spec"] == SPEC_KPI


def test_inflight_report_request_rejected_creates_no_row(db, seed):
    cid, uid, _ = _ids(seed)
    req = _inflight_report_request(db, cid, uid)
    approvals_service.mark_decided(req, user_id=uid, status="rejected", reason="gerek yok")
    db.commit()
    assert _counts(db)["reports"] == 0


# --------------------------------------------------------------------------- #
# 4. Tenant isolation — company_id comes from the request row, NEVER the payload
# --------------------------------------------------------------------------- #
def test_applier_ignores_smuggled_company_id_in_payload(db, seed):
    a_cid, a_uid, _ = _ids(seed, "a")
    b_cid, b_uid, _ = _ids(seed, "b")
    # A crafted payload trying to smuggle another company's ids must be ignored —
    # the applier always uses req.company_id / req.requested_by.
    req = approvals_service.create_request(
        db, company_id=a_cid, project_id=None, kind="agent_create_report",
        target_table="reports", target_id=None,
        payload={"title": "X", "spec": SPEC_TABLE,
                 "company_id": str(b_cid), "owner_id": str(b_uid)},
        description="X", requested_by=a_uid, proposed_by_agent=True,
    )
    db.commit()
    created = approvals_service.apply_request(db, req)
    db.commit()

    report = db.get(Report, uuid.UUID(created["id"]))
    assert report.company_id == a_cid        # from req, not the payload's b_cid
    assert report.owner_id == a_uid


# --------------------------------------------------------------------------- #
# Endpoint round-trip: propose via /ai/agent → approve via /approvals → navigate
# --------------------------------------------------------------------------- #
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


def test_endpoint_propose_returns_draft_no_request(client, seed, db, monkeypatch):
    """CR-039 — through the agent endpoint, propose_report attaches a DRAFT (spec,
    no request_id) and creates NO approval request. Creation is the user's separate
    POST /studio/reports (the OLUŞTUR click), not an approve step."""
    director = seed["a"]["users"][ROLE_DIRECTOR]
    cid, _, _ = _ids(seed)

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use", [_Block(type="tool_use", name="propose_report",
                         input={"title": "Daire Tipi Kârlılık", "spec": SPEC_TABLE}, id="t0")])
        return _Resp("end_turn", [_Block(type="text",
                     text="Taslağı hazırladım — düzenleyebilir veya Oluştur'a basabilirsin.")])

    monkeypatch.setattr(ai_service, "_client", lambda: _Client(responder))
    client.login(director)

    r = client.post("/api/v1/ai/agent",
                    json={"messages": [{"role": "user", "content": "daire tipine göre kârlılık raporu yap"}]})
    assert r.status_code == 200, r.text
    pa = r.json()["data"]["proposed_actions"][0]
    assert pa["kind"] == "draft_report"
    assert pa["spec"] == SPEC_TABLE          # the card previews without a refetch
    assert "request_id" not in pa
    # The agent created NO approval request and NO report row — the user creates it.
    assert _pending(db, cid, "agent_create_report") == []
    assert _counts(db)["reports"] == 0


# --------------------------------------------------------------------------- #
# 5. "Bu rapor hakkında sor" — grounded AND read-only (zero mutation)
# --------------------------------------------------------------------------- #
def test_ask_about_report_is_read_only_and_grounded(client, seed, db, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    cid, uid, _ = _ids(seed)
    report = creators.create_report(
        db, company_id=cid, owner_id=uid, created_by=uid,
        title="Daire Tipi Kârlılık", spec=SPEC_TABLE,
    )
    db.commit()
    before = _counts(db)

    captured = {}

    def responder(call, kw):
        captured["system"] = kw.get("system", "")
        return _Resp("end_turn", [_Block(type="text", text="Bu raporda en yüksek kalem X.")])

    monkeypatch.setattr(ai_service, "_client", lambda: _Client(responder))
    client.login(director)

    r = client.post("/api/v1/ai/agent", json={
        "messages": [{"role": "user", "content": "bu raporda en yüksek maliyet kalemi ne?"}],
        "report_id": str(report.id),
    })
    assert r.status_code == 200, r.text
    # The report grounded the prompt (title injected as read-only context).
    assert "Daire Tipi Kârlılık" in captured["system"]
    assert "RAPOR BAĞLAMI" in captured["system"]
    # Zero mutations — asking is read-only.
    assert _counts(db) == before


def test_ask_about_report_cross_company_is_404(client, seed, db, monkeypatch):
    # A report owned by company B is invisible to a company-A director.
    b_cid, b_uid, _ = _ids(seed, "b")
    b_report = creators.create_report(
        db, company_id=b_cid, owner_id=b_uid, created_by=b_uid,
        title="B Raporu", spec=SPEC_TABLE,
    )
    db.commit()

    def responder(call, kw):
        return _Resp("end_turn", [_Block(type="text", text="x")])

    monkeypatch.setattr(ai_service, "_client", lambda: _Client(responder))
    client.login(seed["a"]["users"][ROLE_DIRECTOR])

    r = client.post("/api/v1/ai/agent", json={
        "messages": [{"role": "user", "content": "bu rapor?"}],
        "report_id": str(b_report.id),
    })
    assert r.status_code == 404, r.text
