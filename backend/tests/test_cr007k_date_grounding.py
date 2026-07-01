"""CR-007-K / CR-011-A — date grounding: the agent must resolve relative time
phrases ("son 6 ay") against the real server date, not a guessed year.

Original CR-007-K bug: run_agent never told the model today's date, so "son 6
ayda" on 2026-06-15 resolved to Jul–Dec 2024 (18 months off) and returned empty.
The stopgap injected "BUGÜN: <today>" and let the MODEL compute the window.

CR-011-A §1.2 removes that stopgap: the SERVER now resolves relative windows. The
model passes a named ``relative_window`` and ``resolve_window`` turns it into
literal ISO dates — the model never does date math.
"""
from datetime import date

from app.constants import ROLE_DIRECTOR
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
        self.last_kwargs = None

    def create(self, **kw):
        self.last_kwargs = kw
        r = self._r(self.calls, kw)
        self.calls += 1
        return r


class _Client:
    def __init__(self, responder):
        self.messages = _Messages(responder)


def _patch(monkeypatch, responder):
    c = _Client(responder)
    monkeypatch.setattr(ai_service, "_client", lambda: c)
    return c


# --------------------------------------------------------------------------- #
# Unit: date guidance is grounding context only — NO model date math
# --------------------------------------------------------------------------- #
def test_date_guidance_contains_today_and_forbids_math():
    s = agent_service._date_guidance(date(2026, 6, 15))
    assert "BUGÜN: 2026-06-15" in s
    assert "relative_window" in s            # relative periods routed to the server
    assert "HESABI YAPMA" in s               # the model must not compute dates


def test_run_agent_injects_today_into_system_prompt(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    client = _patch(monkeypatch, lambda call, kw: _Resp("end_turn", [_Block(type="text", text="ok")]))

    agent_service.run_agent(db, cid, [{"role": "user", "content": "merhaba"}], today=date(2026, 6, 15))

    assert "BUGÜN: 2026-06-15" in client.messages.last_kwargs["system"]


def test_run_agent_defaults_today_to_server_date(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    client = _patch(monkeypatch, lambda call, kw: _Resp("end_turn", [_Block(type="text", text="ok")]))

    agent_service.run_agent(db, cid, [{"role": "user", "content": "x"}])  # no today
    assert f"BUGÜN: {date.today():%Y-%m-%d}" in client.messages.last_kwargs["system"]


# --------------------------------------------------------------------------- #
# Unit: server-side window resolution (the model never computes)
# --------------------------------------------------------------------------- #
def test_resolve_window_rolling_and_calendar():
    today = date(2026, 6, 15)
    # Rolling "last 6 months" counts back from today.
    assert agent_service.resolve_window("son_6_ay", today) == (date(2025, 12, 15), today)
    assert agent_service.resolve_window("son_3_ay", today) == (date(2026, 3, 15), today)
    # Calendar windows align to boundaries.
    assert agent_service.resolve_window("bu_ay", today) == (date(2026, 6, 1), today)
    assert agent_service.resolve_window("gecen_ay", today) == (date(2026, 5, 1), date(2026, 5, 31))
    assert agent_service.resolve_window("bu_yil", today) == (date(2026, 1, 1), today)
    assert agent_service.resolve_window("gecen_yil", today) == (date(2025, 1, 1), date(2025, 12, 31))
    assert agent_service.resolve_window("bu_ceyrek", today) == (date(2026, 4, 1), today)
    assert agent_service.resolve_window("gecen_ceyrek", today) == (date(2026, 1, 1), date(2026, 3, 31))
    # Unknown window leaves dates to the caller.
    assert agent_service.resolve_window("bilinmeyen", today) == (None, None)


def test_resolve_window_year_boundary_clamps_day():
    # Jan 31 minus 6 calendar months → Jul 31 of the prior year (no Feb-30 crash).
    today = date(2026, 1, 31)
    df, dt = agent_service.resolve_window("son_6_ay", today)
    assert (df, dt) == (date(2025, 7, 31), today)


# --------------------------------------------------------------------------- #
# Loop: a model that passes relative_window gets literal, correct-year dates
# --------------------------------------------------------------------------- #
def test_son_6_ay_resolved_server_side_to_correct_year(db, seed, monkeypatch):
    """The model passes ``relative_window='son_6_ay'`` (no date math). The server
    resolves it so the vendor tool receives 2025-12-15 .. 2026-06-15 — never 2024."""
    cid = seed["a"]["company"].id
    today = date(2026, 6, 15)

    captured: dict = {}

    def fake_vendor(db_, company_id_, **params):
        captured.update(params)
        return {"summary": {"vendor_name": params.get("vendor_name"), "matched_names": [],
                            "total_try": "0.00", "by_month": [], "by_category": [], "by_project": []},
                "records": [], "row_count": 0, "truncated": False}

    monkeypatch.setitem(
        agent_service.TOOL_REGISTRY, "get_vendor_spend",
        (fake_vendor, agent_service.TOOL_REGISTRY["get_vendor_spend"][1]),
    )

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use", [_Block(type="tool_use", name="get_vendor_spend",
                                             input={"vendor_name": "Bozkurt beton",
                                                    "relative_window": "son_6_ay"}, id="t0")])
        return _Resp("end_turn", [_Block(type="text", text="Sonuç hazır.")])

    _patch(monkeypatch, responder)
    out = agent_service.run_agent(
        db, cid, [{"role": "user", "content": "Bozkurt beton ile son 6 ayda ne kadar iş yaptık?"}],
        today=today,
    )

    assert out["tools_used"] == ["get_vendor_spend"]
    # The window lands on the correct year — 2025-12-15 .. 2026-06-15 — not 2024.
    assert captured["date_from"] == date(2025, 12, 15)
    assert captured["date_to"] == date(2026, 6, 15)
    assert captured["date_from"].year != 2024
    # The tool never sees the raw relative_window token — only literal dates.
    assert "relative_window" not in captured


def test_explicit_dates_win_over_relative_window(db, seed, monkeypatch):
    """If the model passes explicit dates (user gave them), the server keeps them
    and does not overwrite with a relative window."""
    cid = seed["a"]["company"].id
    captured: dict = {}

    def fake_vendor(db_, company_id_, **params):
        captured.update(params)
        return {"summary": {}, "records": [], "row_count": 0, "truncated": False}

    monkeypatch.setitem(
        agent_service.TOOL_REGISTRY, "get_vendor_spend",
        (fake_vendor, agent_service.TOOL_REGISTRY["get_vendor_spend"][1]),
    )

    agent_service.execute_tool(
        db, cid, "get_vendor_spend",
        {"vendor_name": "X", "date_from": "2026-02-01", "date_to": "2026-02-28",
         "relative_window": "son_6_ay"},
        [], [], set(), date(2026, 6, 15),
    )
    assert captured["date_from"] == date(2026, 2, 1)
    assert captured["date_to"] == date(2026, 2, 28)


def test_relative_window_in_date_tool_schemas():
    """The four date-aware tools expose relative_window; non-date tools do not."""
    schemas = {t["name"]: t for t in agent_service.build_tool_schemas()}
    for name in ("query_cost_entries", "query_client_invoices", "get_vendor_spend", "compare_vendors"):
        assert "relative_window" in schemas[name]["input_schema"]["properties"], name
    assert "relative_window" not in schemas["list_projects"]["input_schema"]["properties"]
