"""CR-007-J — test-plan gap coverage + regression backstop (§11).

Rounds out the §11 checklist not already covered by the A–E suites:
- get_cashflow window math (§11.1)
- query_client_invoices group_by sums (§11.1)
- read-only guarantee: no tool writes to the DB (§11.2)
- endpoint degradation when Claude raises mid-loop (§11.4)
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.services import agent as agent_service
from app.services import agent_tools as T
from app.services import ai as ai_service


def _cost(db, project, cid, uid, **kw):
    base = dict(
        project_id=project.id, company_id=cid, entry_date=date(2026, 1, 15),
        cost_category="material_concrete", supplier_name="Akçansa",
        amount_try=Decimal("1000"), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal("1000"), payment_status="unpaid",
        entry_type="actual", amount_paid_try=Decimal("0"), created_by=uid,
    )
    base.update(kw)
    c = CostEntry(**base)
    db.add(c)
    db.flush()
    return c


def _invoice(db, project, cid, uid, **kw):
    base = dict(
        project_id=project.id, company_id=cid, invoice_number="HAK-X",
        invoice_date=date(2026, 1, 10), invoice_type="hakedis",
        amount_try=Decimal("1000"), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal("1000"), net_due_try=Decimal("1000"),
        due_date=date(2026, 2, 10), payment_status="unpaid",
        amount_received_try=Decimal("0"), created_by=uid,
    )
    base.update(kw)
    i = ClientInvoice(**base)
    db.add(i)
    db.flush()
    return i


# --------------------------------------------------------------------------- #
# get_cashflow — window math (§11.1)
# --------------------------------------------------------------------------- #
def test_get_cashflow_projection_window_math(db, seed):
    cid = seed["a"]["company"].id
    p = seed["a"]["project"]
    uid = seed["a"]["users"][ROLE_DIRECTOR].id
    today = date(2026, 6, 15)
    # Unpaid cost due in 16 days (within 30) — planned outflow 10,000.
    _cost(db, p, cid, uid, total_with_vat_try=Decimal("10000"), amount_try=Decimal("10000"),
          payment_status="unpaid", payment_due_date=date(2026, 7, 1))
    # Outstanding invoice due in 20 days (within 30) — expected inflow 4,000.
    _invoice(db, p, cid, uid, invoice_number="HAK-CF", net_due_try=Decimal("4000"),
             total_with_vat_try=Decimal("4000"), amount_try=Decimal("4000"),
             due_date=date(2026, 7, 5), payment_status="unpaid")
    db.commit()

    out = T.get_cashflow(db, cid, today=today)
    w30 = next(w for w in out["summary"]["projection"] if w["days"] == 30)
    assert w30["planned_out_try"] == "10000.00"
    assert w30["expected_in_try"] == "4000.00"
    assert w30["net_need_try"] == "6000.00"
    assert w30["shortfall"] is True
    assert out["row_count"] > 0  # monthly series present


def test_get_cashflow_focus_window(db, seed):
    cid = seed["a"]["company"].id
    out = T.get_cashflow(db, cid, window_days=60, today=date(2026, 6, 15))
    assert out["summary"]["focus_window"]["days"] == 60


# --------------------------------------------------------------------------- #
# query_client_invoices — group_by sums (§11.1)
# --------------------------------------------------------------------------- #
def test_query_client_invoices_group_by_month(db, seed):
    cid = seed["a"]["company"].id
    p = seed["a"]["project"]
    uid = seed["a"]["users"][ROLE_DIRECTOR].id
    _invoice(db, p, cid, uid, invoice_number="HAK-1", invoice_date=date(2026, 1, 5),
             total_with_vat_try=Decimal("12000"), net_due_try=Decimal("12000"))
    _invoice(db, p, cid, uid, invoice_number="HAK-2", invoice_date=date(2026, 2, 5),
             total_with_vat_try=Decimal("6000"), net_due_try=Decimal("6000"))
    db.commit()

    groups = T.query_client_invoices(db, cid, group_by="month")["summary"]["groups"]
    by_key = {g["key"]: g["total_with_vat_try"] for g in groups}
    assert by_key["2026-01"] == "12000.00"
    assert by_key["2026-02"] == "6000.00"


# --------------------------------------------------------------------------- #
# Read-only guarantee (§11.2)
# --------------------------------------------------------------------------- #
def test_tools_never_write_to_db(db, seed):
    cid = seed["a"]["company"].id
    p = seed["a"]["project"]
    uid = seed["a"]["users"][ROLE_DIRECTOR].id
    sub = Subcontractor(project_id=p.id, company_id=cid, name="Akçansa",
                        contract_value_try=Decimal("1000"), status="active")
    db.add(sub)
    _cost(db, p, cid, uid, subcontractor_id=sub.id)
    _invoice(db, p, cid, uid, invoice_number="HAK-RO")
    db.commit()

    def counts():
        return (
            db.execute(select(func.count()).select_from(CostEntry)).scalar(),
            db.execute(select(func.count()).select_from(ClientInvoice)).scalar(),
            db.execute(select(func.count()).select_from(Subcontractor)).scalar(),
        )

    before = counts()
    # Exercise every read-only tool.
    T.list_projects(db, cid)
    T.get_project_financials(db, cid, p.id)
    T.query_cost_entries(db, cid, group_by="category")
    T.query_client_invoices(db, cid, group_by="month")
    T.query_subcontractors(db, cid)
    T.get_vendor_spend(db, cid, vendor_name="Akçansa")
    T.compare_vendors(db, cid)
    T.get_cashflow(db, cid, today=date(2026, 6, 15))
    T.get_overdue_payments(db, cid, today=date(2026, 6, 15))
    # CR-011-B — new read-only tools are equally write-free.
    T.get_equipment_utilisation(db, cid, today=date(2026, 6, 15))
    T.get_budget_variance(db, cid)
    T.get_retention_summary(db, cid)
    T.get_assurance_findings(db, cid)
    T.create_chart(chart_type="bar", title="t", x_key="k",
                   series=[{"key": "v", "label": "V", "type": "bar"}], data=[{"k": "a", "v": 1}])
    db.commit()

    assert counts() == before  # no inserts/updates/deletes from any tool


def test_registry_has_no_write_capable_tool():
    """The registry exposes only the fixed read-only tools — no raw-SQL / write tool.
    CR-011-B adds four more read-only tools; the read-only guarantee is unchanged."""
    names = set(agent_service.TOOL_REGISTRY)
    assert names == {
        "list_projects", "get_project_financials", "query_cost_entries",
        "query_client_invoices", "query_subcontractors", "get_vendor_spend",
        "compare_vendors", "get_cashflow", "get_overdue_payments",
        # CR-011-B
        "get_equipment_utilisation", "get_budget_variance",
        "get_retention_summary", "get_assurance_findings",
    }
    for forbidden in ("run_sql", "execute_sql", "raw_sql", "insert", "update", "delete"):
        assert forbidden not in names


# --------------------------------------------------------------------------- #
# Degradation via the endpoint when Claude raises mid-loop (§11.4)
# --------------------------------------------------------------------------- #
class _RaisingMessages:
    def create(self, **kw):
        raise RuntimeError("upstream 529 overloaded")


class _RaisingClient:
    messages = _RaisingMessages()


def test_endpoint_degrades_when_claude_raises(client, seed, monkeypatch):
    monkeypatch.setattr(ai_service, "_client", lambda: _RaisingClient())
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/ai/agent", json={"messages": [{"role": "user", "content": "Akçansa?"}]})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["answer_markdown"] == agent_service.DEGRADED_MESSAGE
    assert data["charts"] == []
    assert data["citations"] == []
    assert data["tools_used"] == []
