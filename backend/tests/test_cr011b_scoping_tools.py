"""CR-011-B — domain scoping + new read-only tools (§2).

Covers the four new tools (equipment utilisation, budget-vs-actual variance,
retention/teminat, CR-022 assurance findings) with crafted + empty fixtures, the
scope → preamble/tool-subset/context wiring, genel-unchanged, and company
isolation. All tools stay read-only and company-scoped.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.ai_alert import AIAlert
from app.models.budget_line_item import BudgetLineItem
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.equipment_log import EquipmentLog
from app.services import agent as agent_service
from app.services import agent_tools as tools
from app.services import ai as ai_service


def _cid_uid_pid(seed, label="a"):
    return (seed[label]["company"].id,
            seed[label]["users"][ROLE_DIRECTOR].id,
            seed[label]["project"].id)


def _cost(pid, cid, uid, *, cat, total, amount=None, vat=Decimal("0"), etype="actual"):
    amount = amount if amount is not None else total
    return CostEntry(
        project_id=pid, company_id=cid, entry_date=date(2026, 3, 1), cost_category=cat,
        supplier_name="X", amount_try=Decimal(amount), vat_amount_try=Decimal(vat),
        total_with_vat_try=Decimal(total), payment_status="unpaid", entry_type=etype,
        created_by=uid,
    )


# --------------------------------------------------------------------------- #
# Tool: get_equipment_utilisation
# --------------------------------------------------------------------------- #
def test_equipment_utilisation_positive(db, seed):
    cid, uid, pid = _cid_uid_pid(seed)
    db.add(EquipmentLog(
        project_id=pid, company_id=cid, equipment_name="Vinç", ownership_type="rented",
        rate_try=Decimal("1000"), rate_unit="day",
        deployment_start=date(2026, 1, 1), deployment_end=date(2026, 1, 10),
        fuel_maintenance_try=Decimal("500"),
    ))
    db.add(EquipmentLog(
        project_id=pid, company_id=cid, equipment_name="Ekskavatör", ownership_type="owned",
        deployment_start=date(2026, 5, 1), deployment_end=None,
        fuel_maintenance_try=Decimal("300"),
    ))
    db.commit()

    out = tools.get_equipment_utilisation(db, cid, today=date(2026, 6, 19))
    s = out["summary"]
    assert s["equipment_count"] == 2
    assert s["active_count"] == 1            # Ekskavatör still deployed
    assert s["ended_count"] == 1             # Vinç returned 2026-01-10
    # Rented Vinç: 10 days × 1000 = 10.000; owned accrues no rental.
    assert s["total_estimated_rental_try"] == "10000.00"
    assert s["total_fuel_maintenance_try"] == "800.00"
    assert set(s["by_ownership"]) == {"rented", "owned"}
    vinc = next(r for r in out["records"] if r["name"] == "Vinç")
    assert vinc["deployment_days"] == 10
    assert vinc["estimated_rental_try"] == "10000.00"
    assert vinc["is_active"] is False
    assert "equipment?highlight=" in vinc["deep_link"]


def test_equipment_utilisation_empty(db, seed):
    cid, _, _ = _cid_uid_pid(seed)
    out = tools.get_equipment_utilisation(db, cid, today=date(2026, 6, 19))
    assert out["summary"]["equipment_count"] == 0
    assert out["records"] == [] and out["row_count"] == 0


# --------------------------------------------------------------------------- #
# Tool: get_budget_variance
# --------------------------------------------------------------------------- #
def test_budget_variance_positive(db, seed):
    cid, uid, pid = _cid_uid_pid(seed)
    db.add(BudgetLineItem(project_id=pid, company_id=cid, cost_category="material_concrete",
                          original_budget_try=Decimal("10000")))
    db.add(BudgetLineItem(project_id=pid, company_id=cid, cost_category="material_steel",
                          original_budget_try=Decimal("5000")))
    db.add(_cost(pid, cid, uid, cat="material_concrete", total="12000", amount="10000", vat="2000"))
    db.add(_cost(pid, cid, uid, cat="material_steel", total="3000"))
    db.commit()

    out = tools.get_budget_variance(db, cid)
    s = out["summary"]
    assert s["total_revised_budget_try"] == "15000.00"
    assert s["total_actual_try"] == "15000.00"
    assert s["total_variance_try"] == "0.00"
    assert s["over_budget_category_count"] == 1
    assert s["over_budget"] is False
    # Most over-budget first.
    first = out["records"][0]
    assert first["cost_category"] == "material_concrete"
    assert first["over_budget"] is True
    assert first["variance_try"] == "-2000.00"
    steel = next(r for r in out["records"] if r["cost_category"] == "material_steel")
    assert steel["variance_try"] == "2000.00"
    assert steel["over_budget"] is False


def test_budget_variance_ignores_forecast_only_entries(db, seed):
    """Only entry_type='actual' costs count as actual; a forecast entry must not."""
    cid, uid, pid = _cid_uid_pid(seed)
    db.add(BudgetLineItem(project_id=pid, company_id=cid, cost_category="labor",
                          original_budget_try=Decimal("8000")))
    db.add(_cost(pid, cid, uid, cat="labor", total="9000", etype="forecast"))
    db.commit()
    out = tools.get_budget_variance(db, cid)
    row = next(r for r in out["records"] if r["cost_category"] == "labor")
    assert row["actual_try"] == "0.00"
    assert row["over_budget"] is False


def test_budget_variance_empty(db, seed):
    cid, _, _ = _cid_uid_pid(seed)
    out = tools.get_budget_variance(db, cid)
    assert out["summary"]["category_count"] == 0
    assert out["records"] == []


# --------------------------------------------------------------------------- #
# Tool: get_retention_summary
# --------------------------------------------------------------------------- #
def _invoice(pid, cid, uid, *, number, retention, total="120000"):
    return ClientInvoice(
        project_id=pid, company_id=cid, invoice_number=number, invoice_date=date(2026, 1, 15),
        amount_try=Decimal("100000"), vat_amount_try=Decimal("20000"),
        total_with_vat_try=Decimal(total), retention_amount_try=Decimal(retention),
        net_due_try=Decimal("114000"), due_date=date(2026, 2, 15), created_by=uid,
    )


def test_retention_summary_positive(db, seed):
    cid, uid, pid = _cid_uid_pid(seed)
    db.add(_invoice(pid, cid, uid, number="HK-1", retention="6000"))
    db.add(_invoice(pid, cid, uid, number="HK-2", retention="4000"))
    db.add(_invoice(pid, cid, uid, number="HK-3", retention="0"))  # no retention -> excluded
    db.commit()

    out = tools.get_retention_summary(db, cid)
    s = out["summary"]
    assert s["total_retention_held_try"] == "10000.00"
    assert s["invoice_count"] == 2
    assert s["project_count"] == 1
    assert len(s["by_project"]) == 1
    assert out["row_count"] == 2
    assert all("invoices?highlight=" in r["deep_link"] for r in out["records"])


def test_retention_summary_empty(db, seed):
    cid, uid, pid = _cid_uid_pid(seed)
    db.add(_invoice(pid, cid, uid, number="HK-9", retention="0"))
    db.commit()
    out = tools.get_retention_summary(db, cid)
    assert out["summary"]["total_retention_held_try"] == "0.00"
    assert out["records"] == []


# --------------------------------------------------------------------------- #
# Tool: get_assurance_findings (CR-022)
# --------------------------------------------------------------------------- #
def _alert(cid, pid, **kw):
    base = dict(
        company_id=cid, project_id=pid, alert_type="assurance_duplicate", severity="high",
        title_tr="Olası mükerrer fatura", body_tr="İki fatura aynı görünüyor.",
        dedup_key="dup:abc", source_type="client_invoice",
    )
    base.update(kw)
    return AIAlert(**base)


def test_assurance_findings_positive(db, seed):
    import uuid
    cid, _, pid = _cid_uid_pid(seed)
    src = uuid.uuid4()
    db.add(_alert(cid, pid, source_id=src, dedup_key="dup:1"))
    db.add(_alert(cid, pid, severity="medium", dedup_key="dup:2", source_id=uuid.uuid4()))
    # A legacy health alert (no dedup_key) is NOT an assurance finding -> excluded.
    db.add(AIAlert(company_id=cid, project_id=pid, alert_type="margin_warning",
                   severity="high", title_tr="Marj", body_tr="..."))
    db.commit()

    out = tools.get_assurance_findings(db, cid)
    s = out["summary"]
    assert s["finding_count"] == 2
    assert s["by_severity"] == {"high": 1, "medium": 1}
    high = next(r for r in out["records"] if r["severity"] == "high")
    assert "invoices?highlight=" in high["deep_link"]


def test_assurance_findings_excludes_active_dismissals(db, seed):
    cid, _, pid = _cid_uid_pid(seed)
    future = datetime.now(timezone.utc) + timedelta(days=3)
    db.add(_alert(cid, pid, dedup_key="dup:d", is_dismissed=True, dismissed_until=future))
    db.commit()
    out = tools.get_assurance_findings(db, cid)
    assert out["summary"]["finding_count"] == 0


def test_assurance_findings_severity_filter(db, seed):
    import uuid
    cid, _, pid = _cid_uid_pid(seed)
    db.add(_alert(cid, pid, dedup_key="dup:h", source_id=uuid.uuid4(), severity="high"))
    db.add(_alert(cid, pid, dedup_key="dup:l", source_id=uuid.uuid4(), severity="low"))
    db.commit()
    out = tools.get_assurance_findings(db, cid, severity="low")
    assert out["summary"]["finding_count"] == 1
    assert out["records"][0]["severity"] == "low"


# --------------------------------------------------------------------------- #
# Company isolation (every new tool)
# --------------------------------------------------------------------------- #
def test_new_tools_company_isolation(db, seed):
    a_cid, a_uid, a_pid = _cid_uid_pid(seed, "a")
    b_cid = seed["b"]["company"].id
    db.add(EquipmentLog(project_id=a_pid, company_id=a_cid, equipment_name="A-Vinç",
                        ownership_type="rented", rate_try=Decimal("1"), rate_unit="day",
                        deployment_start=date(2026, 1, 1)))
    db.add(BudgetLineItem(project_id=a_pid, company_id=a_cid, cost_category="labor",
                          original_budget_try=Decimal("1")))
    db.add(_invoice(a_pid, a_cid, a_uid, number="A-HK", retention="5"))
    db.add(_alert(a_cid, a_pid, source_id=None, project_id=a_pid))
    db.commit()

    # Company B sees none of A's rows.
    assert tools.get_equipment_utilisation(db, b_cid, today=date(2026, 6, 19))["summary"]["equipment_count"] == 0
    assert tools.get_budget_variance(db, b_cid)["summary"]["category_count"] == 0
    assert tools.get_retention_summary(db, b_cid)["summary"]["invoice_count"] == 0
    assert tools.get_assurance_findings(db, b_cid)["summary"]["finding_count"] == 0


# --------------------------------------------------------------------------- #
# Domain scoping (§2.1) — preamble + tool subset + context
# --------------------------------------------------------------------------- #
def test_scoped_tool_schemas_subset_per_scope():
    full = {t["name"] for t in agent_service.build_tool_schemas()}
    gider = {t["name"] for t in agent_service.scoped_tool_schemas("gider")}
    # Always-on tools present.
    assert {"create_chart", "list_projects"} <= gider
    # Gider domain tools present; gelir/hakedis tools absent.
    assert {"query_cost_entries", "get_budget_variance", "get_vendor_spend"} <= gider
    assert "query_client_invoices" not in gider
    assert "get_retention_summary" not in gider
    assert gider < full

    gelir = {t["name"] for t in agent_service.scoped_tool_schemas("gelir")}
    assert {"query_client_invoices", "get_retention_summary"} <= gelir
    assert "get_vendor_spend" not in gelir


def test_scoped_tool_schemas_genel_is_full():
    full = {t["name"] for t in agent_service.build_tool_schemas()}
    assert {t["name"] for t in agent_service.scoped_tool_schemas(None)} == full
    # Unknown scope falls back to genel (graceful, not rejected).
    assert {t["name"] for t in agent_service.scoped_tool_schemas("uzay")} == full


def test_scope_preamble_per_domain():
    assert "Gider Agent" in agent_service._scope_preamble("gider")
    assert "Finans Agent" in agent_service._scope_preamble("finans")
    assert agent_service._scope_preamble(None) == ""


# --- minimal fake client to inspect what the model receives ---------------- #
class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _Messages:
    def __init__(self):
        self.last = None

    def create(self, **kw):
        self.last = kw
        return _Resp("end_turn", [_Block(type="text", text="ok")])


class _Client:
    def __init__(self):
        self.messages = _Messages()


def _patch(monkeypatch):
    c = _Client()
    monkeypatch.setattr(ai_service, "_client", lambda: c)
    return c


def test_run_agent_scope_passes_subset_and_preamble(db, seed, monkeypatch):
    cid, uid, pid = _cid_uid_pid(seed)
    # Seed a cost so the gider pre-loaded context has a real figure.
    db.add(_cost(pid, cid, uid, cat="material_concrete", total="1000"))
    db.commit()
    client = _patch(monkeypatch)

    agent_service.run_agent(db, cid, [{"role": "user", "content": "giderler?"}],
                            today=date(2026, 6, 19), scope="gider")

    sent_tools = {t["name"] for t in client.messages.last["tools"]}
    assert "get_budget_variance" in sent_tools
    assert "query_client_invoices" not in sent_tools
    system = client.messages.last["system"]
    assert "ALAN ODAĞI" in system and "Gider Agent" in system
    assert "ALAN BAĞLAMI" in system  # pre-loaded headline figure present


def test_run_agent_genel_scope_unchanged(db, seed, monkeypatch):
    cid, _, _ = _cid_uid_pid(seed)
    client = _patch(monkeypatch)
    agent_service.run_agent(db, cid, [{"role": "user", "content": "x"}])  # no scope

    sent_tools = {t["name"] for t in client.messages.last["tools"]}
    assert sent_tools == {t["name"] for t in agent_service.build_tool_schemas()}
    assert "ALAN ODAĞI" not in client.messages.last["system"]


def test_scope_context_defensive_on_empty(db, seed):
    """Pre-loading never raises even with no data — returns a string (possibly 0)."""
    cid, _, _ = _cid_uid_pid(seed)
    ctx = agent_service._scope_context(db, cid, "finans", date(2026, 6, 19))
    assert isinstance(ctx, str) and "Vadesi geçmiş" in ctx
    assert agent_service._scope_context(db, cid, None, date(2026, 6, 19)) == ""
