"""CR-007-B — agentic tool-use loop endpoint.

Mocks the Claude client to drive a scripted tool-use sequence (§11.3): the
headline question runs get_vendor_spend -> create_chart -> compare_vendors and
returns answer_markdown + a multi-series chart (with a total line) + citations.
Also covers the 6-iteration runaway cap, server-side company_id injection, and
graceful degradation.
"""
from datetime import date
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.services import agent as agent_service
from app.services import ai as ai_service


# --------------------------------------------------------------------------- #
# Fake Anthropic client
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
        self._responder = responder
        self.calls = 0

    def create(self, **kw):
        r = self._responder(self.calls, kw)
        self.calls += 1
        return r


class _Client:
    def __init__(self, responder):
        self.messages = _Messages(responder)


def _patch_client(monkeypatch, responder):
    client = _Client(responder)
    monkeypatch.setattr(ai_service, "_client", lambda: client)
    return client


def _seed_vendor_costs(db, seed):
    p = seed["a"]["project"]
    cid = seed["a"]["company"].id
    uid = seed["a"]["users"][ROLE_DIRECTOR].id
    for amt, cat, d in [
        ("1000", "material_concrete", date(2026, 1, 10)),
        ("3000", "material_steel", date(2026, 1, 20)),
        ("500", "material_concrete", date(2026, 2, 5)),
    ]:
        db.add(CostEntry(
            project_id=p.id, company_id=cid, entry_date=d, cost_category=cat,
            supplier_name="Akçansa", amount_try=Decimal(amt), vat_amount_try=Decimal("0"),
            total_with_vat_try=Decimal(amt), payment_status="unpaid", entry_type="actual",
            created_by=uid,
        ))
    db.commit()
    return cid


_CHART_INPUT = {
    "chart_type": "line",
    "title": "Akçansa — Aylık Harcama",
    "x_key": "month",
    "series": [
        {"key": "total", "label": "Toplam", "type": "line"},
        {"key": "beton", "label": "Beton", "type": "line"},
        {"key": "celik", "label": "Çelik", "type": "line"},
    ],
    "data": [
        {"month": "2026-01", "total": 4000, "beton": 1000, "celik": 3000},
        {"month": "2026-02", "total": 500, "beton": 500, "celik": 0},
    ],
    "currency": "TRY",
    "source_note": "Kaynak: maliyet kayıtları",
}


# --------------------------------------------------------------------------- #
# Headline scenario (§5.1 / §11.3)
# --------------------------------------------------------------------------- #
def test_headline_loop_vendor_spend_chart_compare(db, seed, monkeypatch):
    cid = _seed_vendor_costs(db, seed)

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use", [_tool("get_vendor_spend", {"vendor_name": "Akçansa"}, "t0")])
        if call == 1:
            return _Resp("tool_use", [_tool("create_chart", _CHART_INPUT, "t1")])
        if call == 2:
            return _Resp("tool_use", [_tool("compare_vendors", {"top_n": 5}, "t2")])
        return _Resp("end_turn", [_text("Akçansa ile toplam **4.500 ₺** harcama yapıldı.")])

    _patch_client(monkeypatch, responder)

    out = agent_service.run_agent(db, cid, [{"role": "user", "content": "Akçansa ile son 6 ayda ne kadar iş yaptık?"}])

    assert out["tools_used"] == ["get_vendor_spend", "create_chart", "compare_vendors"]
    assert out["answer_markdown"].startswith("Akçansa")
    # One chart, multiple series including a 'total' line.
    assert len(out["charts"]) == 1
    chart = out["charts"][0]
    assert len(chart["series"]) >= 2
    assert any(s["key"] == "total" for s in chart["series"])
    # Citations to the seeded cost entries.
    assert len(out["citations"]) >= 1
    assert all("highlight=" in c["deep_link"] for c in out["citations"])
    assert "generated_at" in out


def test_iteration_cap_stops_runaway(db, seed, monkeypatch):
    cid = seed["a"]["company"].id

    # The model never yields end_turn — always asks for another tool call.
    def responder(call, kw):
        return _Resp("tool_use", [_tool("list_projects", {}, f"t{call}")])

    client = _patch_client(monkeypatch, responder)
    out = agent_service.run_agent(db, cid, [{"role": "user", "content": "döngü"}])

    assert client.messages.calls == agent_service.MAX_ITERATIONS  # 6
    # On the final iteration tool_choice is forced to none.
    assert len(out["tools_used"]) == agent_service.MAX_ITERATIONS


def test_final_iteration_forces_tool_choice_none(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    seen_choices = []

    def responder(call, kw):
        seen_choices.append(kw.get("tool_choice"))
        return _Resp("tool_use", [_tool("list_projects", {}, f"t{call}")])

    _patch_client(monkeypatch, responder)
    agent_service.run_agent(db, cid, [{"role": "user", "content": "x"}])

    assert seen_choices[-1] == {"type": "none"}
    assert all(c == {"type": "auto"} for c in seen_choices[:-1])


# --------------------------------------------------------------------------- #
# execute_tool — server-side company_id injection (§1.2 #4 / §11.2)
# --------------------------------------------------------------------------- #
def test_execute_tool_drops_forged_company_id(db, seed):
    a_cid = seed["a"]["company"].id
    b_cid = seed["b"]["company"].id
    a_dir = seed["a"]["users"][ROLE_DIRECTOR].id
    b_dir = seed["b"]["users"][ROLE_DIRECTOR].id
    db.add(CostEntry(project_id=seed["a"]["project"].id, company_id=a_cid, entry_date=date(2026, 1, 1),
                     cost_category="other", supplier_name="A", amount_try=Decimal("100"),
                     vat_amount_try=Decimal("0"), total_with_vat_try=Decimal("100"),
                     payment_status="unpaid", entry_type="actual", created_by=a_dir))
    db.add(CostEntry(project_id=seed["b"]["project"].id, company_id=b_cid, entry_date=date(2026, 1, 1),
                     cost_category="other", supplier_name="B", amount_try=Decimal("9999"),
                     vat_amount_try=Decimal("0"), total_with_vat_try=Decimal("9999"),
                     payment_status="unpaid", entry_type="actual", created_by=b_dir))
    db.commit()

    # A forged company_id in the tool input must be ignored — scoping uses the
    # company_id argument injected by the executor.
    result = agent_service.execute_tool(
        db, a_cid, "query_cost_entries", {"company_id": str(b_cid)}, [], [], set()
    )
    assert result["summary"]["total_amount_try"] == "100.00"
    assert result["summary"]["entry_count"] == 1


def test_execute_tool_coerces_date_strings(db, seed):
    cid = seed["a"]["company"].id
    out = agent_service.execute_tool(
        db, cid, "query_cost_entries",
        {"date_from": "2026-01-01", "date_to": "2026-12-31"}, [], [], set()
    )
    assert "summary" in out  # ran without error -> dates parsed


def test_execute_tool_unknown_tool_returns_error(db, seed):
    out = agent_service.execute_tool(db, seed["a"]["company"].id, "drop_table", {}, [], [], set())
    assert "error" in out


def test_execute_tool_create_chart_appends_chart(db, seed):
    charts = []
    out = agent_service.execute_tool(
        db, seed["a"]["company"].id, "create_chart", _CHART_INPUT, charts, [], set()
    )
    assert out["ok"] is True
    assert len(charts) == 1


def test_execute_tool_create_chart_rejects_bad_spec(db, seed):
    charts = []
    out = agent_service.execute_tool(
        db, seed["a"]["company"].id, "create_chart", {"chart_type": "line"}, charts, [], set()
    )
    assert "error" in out
    assert charts == []


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
def test_agent_endpoint_empty_messages_422(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/ai/agent", json={"messages": []})
    assert r.status_code == 422


def test_agent_endpoint_degrades_without_api_key(client, seed):
    # No anthropic_api_key configured in tests -> graceful Turkish degradation.
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/ai/agent", json={"messages": [{"role": "user", "content": "merhaba"}]})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["answer_markdown"] == agent_service.DEGRADED_MESSAGE
    assert data["charts"] == [] and data["citations"] == []


def test_agent_endpoint_requires_auth(client):
    r = client.post("/api/v1/ai/agent", json={"messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 401


def test_build_tool_schemas_have_no_company_id():
    """§1.2 #4 — no tool input schema may expose company_id."""
    for t in agent_service.build_tool_schemas():
        props = t["input_schema"].get("properties", {})
        assert "company_id" not in props, t["name"]
