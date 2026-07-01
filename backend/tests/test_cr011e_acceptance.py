"""CR-011-E — acceptance / cross-cutting tests (§5).

Consolidates the Agent-v2 guarantees end-to-end and fills the highest-value gaps
left by the per-sub-CR suites: the propose-not-write invariant through the FULL
agent loop, streaming not dropping charts/citations, flag-for-review on a cost
entry, scope context per domain, and no answer-shape regression.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR
from app.models.ai_alert import AIAlert
from app.models.approval_request import ApprovalRequest
from app.models.budget_line_item import BudgetLineItem
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.dashboard import Dashboard
from app.models.notification import Notification
from app.models.report import Report
from app.models.subcontractor import Subcontractor
from app.services import agent as agent_service
from app.services import agent_actions as actions
from app.services import ai as ai_service
from app.services import approvals as approvals_service

# CR-035: Report/Dashboard included — authoring is propose-only (zero direct write).
BUSINESS_MODELS = [Notification, AIAlert, CostEntry, ClientInvoice, Subcontractor,
                   BudgetLineItem, Report, Dashboard]


# --------------------------------------------------------------------------- #
# Fakes (non-stream + streaming)
# --------------------------------------------------------------------------- #
class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _text(t):
    return _Block(type="text", text=t)


def _tool(name, inp, id="tu"):
    return _Block(type="tool_use", name=name, input=inp, id=id)


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


class _FakeStream:
    def __init__(self, resp, chunks):
        self._resp, self._chunks = resp, chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        return iter(self._chunks)

    def get_final_message(self):
        return self._resp


class _StreamMessages:
    def __init__(self, responder):
        self._r = responder
        self.calls = 0

    def stream(self, **kw):
        resp, chunks = self._r(self.calls, kw)
        self.calls += 1
        return _FakeStream(resp, chunks)

    def create(self, **kw):
        resp, _ = self._r(self.calls, kw)
        self.calls += 1
        return resp


class _StreamClient:
    def __init__(self, responder):
        self.messages = _StreamMessages(responder)


def _ids(seed, label="a"):
    return (seed[label]["company"].id,
            seed[label]["users"][ROLE_DIRECTOR].id,
            seed[label]["project"].id)


def _business_counts(db):
    return {m.__name__: db.execute(select(func.count()).select_from(m)).scalar() for m in BUSINESS_MODELS}


def _invoice(db, pid, cid, uid, number="HK-1"):
    inv = ClientInvoice(
        project_id=pid, company_id=cid, invoice_number=number, invoice_date=date(2026, 1, 15),
        amount_try=Decimal("100000"), vat_amount_try=Decimal("20000"),
        total_with_vat_try=Decimal("120000"), net_due_try=Decimal("114000"),
        due_date=date(2026, 2, 15), created_by=uid,
    )
    db.add(inv)
    db.commit()
    return inv


def _cost(db, pid, cid, uid):
    c = CostEntry(
        project_id=pid, company_id=cid, entry_date=date(2026, 1, 10), cost_category="other",
        supplier_name="Akçansa", amount_try=Decimal("4000"), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal("4000"), payment_status="unpaid", entry_type="actual",
        created_by=uid,
    )
    db.add(c)
    db.commit()
    return c


# --------------------------------------------------------------------------- #
# Invariant through the FULL agent loop: many proposals, zero direct mutations
# --------------------------------------------------------------------------- #
def test_full_loop_all_action_tools_propose_zero_mutations(db, seed, monkeypatch):
    cid, uid, pid = _ids(seed)
    inv = _invoice(db, pid, cid, uid)
    before = _business_counts(db)

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use", [
                _tool("propose_reminder", {"title": "Ara"}, "t0"),
                _tool("propose_flag_invoice",
                      {"target_kind": "client_invoice", "target_id": str(inv.id), "reason": "yüksek"}, "t1"),
                _tool("propose_followup_task", {"title": "Teklif"}, "t2"),
                # CR-035 — authoring a report/dashboard goes through the same propose path.
                _tool("propose_report",
                      {"title": "Kârlılık", "spec": {"metrics": ["cost_try"],
                       "dimensions": ["project"], "viz": "table"}}, "t3"),
                _tool("propose_dashboard",
                      {"title": "Pano", "widgets": [
                          {"id": "w1", "type": "kpi", "title": "Maliyet",
                           "layout": {"x": 0, "y": 0, "w": 3, "h": 2},
                           "spec": {"metrics": ["cost_try"], "viz": "kpi"}}]}, "t4"),
            ])
        return _Resp("end_turn", [_text("Öneriler oluşturuldu, onayınızı bekliyor.")])

    _patch(monkeypatch, responder)
    out = agent_service.run_agent(db, cid, [{"role": "user", "content": "beş eylem"}], user_id=uid)

    # Five proposals surfaced: 3 pending approvals + 2 drafts (report/dashboard).
    assert len(out["proposed_actions"]) == 5
    # CR-039 — report/dashboard are DRAFTS (no request_id), the rest are approvals.
    draft_kinds = {a["kind"] for a in out["proposed_actions"] if "request_id" not in a}
    assert draft_kinds == {"draft_report", "draft_dashboard"}
    pend = db.execute(
        select(ApprovalRequest).where(ApprovalRequest.company_id == cid, ApprovalRequest.status == "pending")
    ).scalars().all()
    # CR-039 — only THREE pending requests now (authoring writes nothing at all).
    assert len(pend) == 3 and all(p.proposed_by_agent for p in pend)
    assert {p.kind for p in pend} == {
        "agent_reminder", "agent_flag_invoice", "agent_task",
    }
    # The whole loop wrote ZERO business rows (the invariant, end-to-end §7).
    assert _business_counts(db) == before


# --------------------------------------------------------------------------- #
# Streaming must not drop charts / citations (§7 / §1.1)
# --------------------------------------------------------------------------- #
_CHART_INPUT = {
    "chart_type": "line", "title": "Akçansa — Aylık", "x_key": "month",
    "series": [{"key": "total", "label": "Toplam", "type": "line"}],
    "data": [{"month": "2026-01", "total": 4000}],
    "currency": "TRY",
}


def test_streaming_preserves_charts_and_citations(db, seed, monkeypatch):
    cid, uid, pid = _ids(seed)
    _cost(db, pid, cid, uid)

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use", [_tool("get_vendor_spend", {"vendor_name": "Akçansa"}, "t0")]), []
        if call == 1:
            return _Resp("tool_use", [_tool("create_chart", _CHART_INPUT, "t1")]), []
        return _Resp("end_turn", [_text("Akçansa **4.000 ₺**.")]), ["Akçansa ", "**4.000 ₺**."]

    monkeypatch.setattr(ai_service, "_client", lambda: _StreamClient(responder))
    events = list(agent_service.run_agent_stream(db, cid, [{"role": "user", "content": "Akçansa?"}]))
    final = events[-1]["data"]
    assert len(final["charts"]) == 1
    assert final["charts"][0]["x_key"] == "month"
    assert len(final["citations"]) >= 1  # streaming kept the citations
    assert "".join(e["text"] for e in events if e["type"] == "delta").strip() == "Akçansa **4.000 ₺**."


# --------------------------------------------------------------------------- #
# Flag-for-review on a COST entry applies only on approval
# --------------------------------------------------------------------------- #
def test_flag_cost_entry_applied_only_on_approval(db, seed):
    cid, uid, pid = _ids(seed)
    cost = _cost(db, pid, cid, uid)
    actions.propose_flag_invoice(db, cid, uid, target_kind="cost_entry",
                                 target_id=str(cost.id), reason="Olağandışı tutar")
    assert db.execute(select(func.count()).select_from(AIAlert)).scalar() == 0

    req = db.execute(
        select(ApprovalRequest).where(ApprovalRequest.kind == "agent_flag_invoice")
    ).scalars().one()
    approvals_service.apply_request(db, req)
    approvals_service.mark_decided(req, user_id=uid, status="approved")
    db.commit()

    alert = db.execute(select(AIAlert).where(AIAlert.company_id == cid)).scalars().one()
    assert alert.source_type == "cost_entry"
    assert str(alert.source_id) == str(cost.id)


# --------------------------------------------------------------------------- #
# Scope context per domain (cheap pre-loaded headline figures)
# --------------------------------------------------------------------------- #
def test_scope_context_each_domain_returns_headline(db, seed):
    cid, uid, pid = _ids(seed)
    _invoice(db, pid, cid, uid)
    _cost(db, pid, cid, uid)
    today = date(2026, 6, 19)
    assert "gider" in agent_service._scope_context(db, cid, "gider", today).lower()
    assert "alacak" in agent_service._scope_context(db, cid, "gelir", today).lower()
    assert "alacak" in agent_service._scope_context(db, cid, "hakedis", today).lower()
    assert "vadesi" in agent_service._scope_context(db, cid, "finans", today).lower()
    assert "güvence" in agent_service._scope_context(db, cid, "belge", today).lower()


# --------------------------------------------------------------------------- #
# No answer-shape regression: a read-only answer keeps the full shape and an
# empty proposed_actions list (§5: "no agent answer regresses").
# --------------------------------------------------------------------------- #
def test_readonly_answer_shape_unchanged_with_empty_proposals(db, seed, monkeypatch):
    cid, uid, _ = _ids(seed)

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use", [_tool("list_projects", {}, "t0")])
        return _Resp("end_turn", [_text("Portföy özeti.")])

    _patch(monkeypatch, responder)
    out = agent_service.run_agent(db, cid, [{"role": "user", "content": "projeler"}], user_id=uid)
    assert out["proposed_actions"] == []
    assert set(out.keys()) == {
        "answer_markdown", "charts", "citations", "tools_used",
        "generated_at", "notes", "query_log_id", "row_counts", "proposed_actions",
        # CR-011 rich steps (additive): per-tool aggregate summaries + token usage.
        "tool_summaries", "usage",
    }


def test_stream_with_scope_smoke(db, seed, monkeypatch):
    """run_agent_stream forwards a scope and still yields a final payload."""
    cid, uid, _ = _ids(seed)

    def responder(call, kw):
        return _Resp("end_turn", [_text("Finans özeti.")]), ["Finans ", "özeti."]

    monkeypatch.setattr(ai_service, "_client", lambda: _StreamClient(responder))
    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "finans?"}], user_id=uid, scope="finans"))
    assert events[-1]["type"] == "final"
    assert events[-1]["data"]["answer_markdown"] == "Finans özeti."
