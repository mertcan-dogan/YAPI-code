"""CR-007 date grounding — the agent must resolve relative time phrases ("son 6
ay") against the real server date, not a guessed year.

Bug: run_agent never told the model today's date, so "son 6 ayda" on 2026-06-15
was resolved to Jul–Dec 2024 (18 months off) and returned empty. Fix injects
"BUGÜN: <today>" into the system prompt.
"""
import re
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
# Unit: the date string is injected into the system prompt
# --------------------------------------------------------------------------- #
def test_date_grounding_contains_today():
    s = agent_service._date_grounding(date(2026, 6, 15))
    assert "BUGÜN: 2026-06-15" in s
    assert "tahmin etme" in s  # explicit "never guess the year"


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
# Loop: a correctly-grounded model derives "son 6 ay" in the right year
# --------------------------------------------------------------------------- #
def test_son_6_ay_resolves_to_correct_year(db, seed, monkeypatch):
    """Simulate a model that reads the injected BUGÜN, computes a 6-month window,
    and calls get_vendor_spend. Assert the tool receives dates in 2025/2026 — the
    correct year — not 2024."""
    cid = seed["a"]["company"].id
    today = date(2026, 6, 15)

    # Capture the params that actually reach the vendor tool (execute_tool has
    # already coerced ISO strings to date objects by then).
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
            # A correct model copies BUGÜN from the system prompt and subtracts 6 months.
            m = re.search(r"BUGÜN: (\d{4})-(\d{2})-(\d{2})", kw["system"])
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            idx = (y * 12 + (mo - 1)) - 6
            fy, fm = idx // 12, idx % 12 + 1
            date_from = f"{fy:04d}-{fm:02d}-{d:02d}"
            date_to = f"{y:04d}-{mo:02d}-{d:02d}"
            return _Resp("tool_use", [_Block(type="tool_use", name="get_vendor_spend",
                                             input={"vendor_name": "Bozkurt beton",
                                                    "date_from": date_from, "date_to": date_to}, id="t0")])
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
