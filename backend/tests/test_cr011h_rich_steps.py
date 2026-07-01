"""CR-011 rich agent steps (PART A/B/C) — real step detail + per-chat usage.

PART A: the ``step`` event carries the cleaned tool args (``input``) + the model's
pre-tool narration (``note``); the final payload gains per-tool ``tool_summaries``
(aggregates only, never raw rows). create_chart's args are skipped (huge series).
PART B: extended thinking is env-gated (OFF by default) and NEVER enabled on the
forced-final iteration (the API rejects thinking + a forced tool_choice); its text
is surfaced on the step and excluded from the answer.
PART C: the final payload carries token ``usage`` summed across every iteration.
"""
from app.config import settings
from app.services import agent as agent_service
from app.services import ai as ai_service


# --------------------------------------------------------------------------- #
# Fake Anthropic client that records call kwargs + carries usage/thinking blocks
# --------------------------------------------------------------------------- #
class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Usage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def _text(t):
    return _Block(type="text", text=t)


def _think(t):
    return _Block(type="thinking", thinking=t)


def _tool(name, inp, id="tu"):
    return _Block(type="tool_use", name=name, input=inp, id=id)


class _Resp:
    def __init__(self, stop_reason, content, usage=None):
        self.stop_reason = stop_reason
        self.content = content
        self.usage = usage


class _FakeStream:
    def __init__(self, resp, chunks):
        self._resp = resp
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        return iter(self._chunks)

    def get_final_message(self):
        return self._resp


class _Messages:
    def __init__(self, responder):
        self._responder = responder
        self.calls = 0
        self.kw_log = []  # every call_kw passed to the model (stream or create)

    def stream(self, **kw):
        self.kw_log.append(kw)
        resp, chunks = self._responder(self.calls, kw)
        self.calls += 1
        return _FakeStream(resp, chunks)

    def create(self, **kw):
        self.kw_log.append(kw)
        resp, _chunks = self._responder(self.calls, kw)
        self.calls += 1
        return resp


class _Client:
    def __init__(self, responder):
        self.messages = _Messages(responder)


def _patch(monkeypatch, responder):
    client = _Client(responder)
    monkeypatch.setattr(ai_service, "_client", lambda: client)
    return client


# call 0: narrate + call list_projects(status=active); call 1: end_turn answer.
def _projects_then_answer(call, kw):
    if call == 0:
        return _Resp("tool_use",
                     [_text("Projeleri tarıyorum."),
                      _tool("list_projects", {"status": "active"}, "t0")],
                     usage=_Usage(100, 20)), []
    return _Resp("end_turn", [_text("Aktif projeniz var.")],
                 usage=_Usage(50, 30)), ["Aktif ", "projeniz var."]


# --------------------------------------------------------------------------- #
# PART A — step carries input + note; final carries tool_summaries; PART C usage
# --------------------------------------------------------------------------- #
def test_step_carries_input_and_note_and_final_summaries_usage(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    _patch(monkeypatch, _projects_then_answer)
    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "Projelerim neler?"}]))

    steps = [e for e in events if e["type"] == "step"]
    assert len(steps) == 1
    s = steps[0]
    assert s["tool"] == "list_projects"
    assert s["input"] == {"status": "active"}        # PART A — cleaned tool args
    assert "company_id" not in s["input"]             # never leaks the tenant id
    assert s["note"] == "Projeleri tarıyorum."        # PART A — pre-tool narration

    final = events[-1]["data"]
    # PART A — per-tool aggregate summary (project_count etc.), not raw rows and
    # not nested breakdowns: pruned to scalars on the server (by_status dropped).
    summ = final["tool_summaries"]["list_projects"]
    assert "project_count" in summ
    assert "records" not in summ
    assert "by_status" not in summ
    assert all(isinstance(v, (str, int, float, bool)) for v in summ.values())
    # PART C — usage summed across both iterations (in 100+50, out 20+30).
    assert final["usage"] == {"input_tokens": 150, "output_tokens": 50}


def test_non_stream_final_also_has_usage_and_summaries(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    _patch(monkeypatch, _projects_then_answer)
    res = agent_service.run_agent(db, cid, [{"role": "user", "content": "x"}])
    assert res["usage"] == {"input_tokens": 150, "output_tokens": 50}
    assert "list_projects" in res["tool_summaries"]


def test_usage_none_keeps_zeroed_shape(db, seed, monkeypatch):
    """A response with no ``.usage`` (degraded / test double) must not crash —
    _accumulate_usage's None-guard keeps the {0, 0} shape."""
    cid = seed["a"]["company"].id

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use", [_tool("list_projects", {}, "t0")], usage=None), []
        return _Resp("end_turn", [_text("ok")], usage=None), []

    _patch(monkeypatch, responder)
    res = agent_service.run_agent(db, cid, [{"role": "user", "content": "x"}])
    assert res["usage"] == {"input_tokens": 0, "output_tokens": 0}


# create_chart's args (full series/data) must be skipped — only an empty input.
def _chart_responder(call, kw):
    if call == 0:
        spec = {
            "chart_type": "line", "title": "Aylık", "x_key": "month",
            "series": [{"key": "v", "label": "Değer", "type": "line"}],
            "data": [{"month": "2026-01", "v": 100}],
        }
        return _Resp("tool_use", [_tool("create_chart", spec, "c0")],
                     usage=_Usage(10, 5)), []
    return _Resp("end_turn", [_text("Grafik hazır.")], usage=_Usage(5, 5)), []


def test_create_chart_step_input_is_empty(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    _patch(monkeypatch, _chart_responder)
    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "Grafik çiz"}]))
    steps = [e for e in events if e["type"] == "step"]
    assert steps[0]["tool"] == "create_chart"
    assert steps[0]["input"] == {}   # PART A — the huge chart payload is not echoed


# --------------------------------------------------------------------------- #
# PART B — thinking is gated by the env flag (OFF by default)
# --------------------------------------------------------------------------- #
def test_thinking_off_by_default_no_param_and_empty_step(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    assert settings.ai_agent_thinking_enabled is False
    client = _patch(monkeypatch, _projects_then_answer)
    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "x"}]))
    # No request carries the thinking param when the flag is off.
    assert all("thinking" not in kw for kw in client.messages.kw_log)
    steps = [e for e in events if e["type"] == "step"]
    assert steps[0]["thinking"] == ""   # nothing surfaced


# Always returns tool_use so the loop runs to the forced-final iteration.
def _always_tool(call, kw):
    return _Resp("tool_use",
                 [_think("Hangi aracı çağırmalıyım?"), _tool("list_projects", {}, f"t{call}")],
                 usage=_Usage(10, 5)), []


def test_thinking_enabled_adds_param_except_on_forced_final(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    monkeypatch.setattr(settings, "ai_agent_thinking_enabled", True)
    client = _patch(monkeypatch, _always_tool)
    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "x"}]))

    kws = client.messages.kw_log
    assert len(kws) == agent_service.MAX_ITERATIONS
    # The forced-final call (tool_choice none) NEVER carries thinking.
    final_kw = kws[-1]
    assert final_kw["tool_choice"] == {"type": "none"}
    assert "thinking" not in final_kw
    # Every earlier auto call enables thinking with the configured budget.
    for kw in kws[:-1]:
        assert kw["tool_choice"] == {"type": "auto"}
        assert kw["thinking"] == {
            "type": "enabled", "budget_tokens": settings.ai_agent_thinking_budget}
    # The thinking text is surfaced on each step.
    steps = [e for e in events if e["type"] == "step"]
    assert steps and all(s["thinking"] == "Hangi aracı çağırmalıyım?" for s in steps)


def test_thinking_text_excluded_from_answer(db, seed, monkeypatch):
    """_text_of must ignore thinking blocks so the answer stays clean."""
    cid = seed["a"]["company"].id
    monkeypatch.setattr(settings, "ai_agent_thinking_enabled", True)

    def responder(call, kw):
        if call == 0:
            return _Resp("tool_use",
                         [_think("düşünüyorum"), _tool("list_projects", {}, "t0")],
                         usage=_Usage(10, 5)), []
        return _Resp("end_turn", [_think("son düşünce"), _text("Net cevap.")],
                     usage=_Usage(5, 5)), []

    _patch(monkeypatch, responder)
    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "x"}]))
    final = events[-1]["data"]
    assert final["answer_markdown"] == "Net cevap."   # thinking text excluded


def test_sse_step_frame_carries_new_fields():
    s = agent_service.sse_event({
        "type": "step", "tool": "list_projects", "label": "Projeler taranıyor…",
        "input": {"status": "active"}, "note": "tarıyorum", "thinking": "düşünce",
    })
    assert "event: step\n" in s
    assert '"input"' in s and '"status": "active"' in s
    assert '"note": "tar' in s
    assert '"thinking": "d' in s
