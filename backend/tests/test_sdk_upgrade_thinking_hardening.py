"""SDK-upgrade hardening — a thinking/SDK incompatibility must NEVER down the agent.

Context: the pinned anthropic==0.42.0 predated the `thinking` parameter, so
messages.create/stream raised TypeError when AI_AGENT_THINKING_ENABLED flipped on
and the whole Yapı Agent went down ("AI şu an kullanılamıyor"). After the SDK
upgrade to 0.112.0 two independent guards make that impossible again:

  (a) capability guard — if the installed SDK doesn't accept `thinking`, never pass
      it (treat the flag as OFF, warn once);
  (b) per-call fallback — if a thinking-enabled call still fails *because of*
      thinking, strip it and retry the SAME call once so the user still gets an
      answer instead of an outage.

These tests cover both. They use a fake Anthropic client (no network) whose
`create`/`stream` *signatures* are controlled so the capability guard introspects
them exactly as it would the real SDK.
"""
import pytest

from app.config import settings
from app.services import agent as agent_service
from app.services import ai as ai_service


# --------------------------------------------------------------------------- #
# Fakes — signature-controlled so _create_accepts_thinking sees a real shape.
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


class _Resp:
    def __init__(self, stop_reason, content, usage=None):
        self.stop_reason = stop_reason
        self.content = content
        self.usage = usage


def _answer():
    return _Resp("end_turn", [_text("Net cevap.")], usage=_Usage(10, 5))


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


# --- (a) capability guard: an "old SDK" whose create/stream lack a thinking
#     parameter AND have no **kwargs. Passing thinking= would TypeError, so the
#     guard must keep it off. The explicit signature is what the guard reads.
class _OldMessages:
    def __init__(self):
        self.kw_log = []

    def create(self, *, model, max_tokens, messages, system=None, tools=None,
               tool_choice=None, timeout=None):
        self.kw_log.append({"model": model, "max_tokens": max_tokens,
                            "system": system, "tools": tools,
                            "tool_choice": tool_choice, "messages": messages,
                            "timeout": timeout})
        return _answer()

    def stream(self, *, model, max_tokens, messages, system=None, tools=None,
               tool_choice=None, timeout=None):
        self.kw_log.append({"model": model, "max_tokens": max_tokens,
                            "system": system, "tools": tools,
                            "tool_choice": tool_choice, "messages": messages,
                            "timeout": timeout})
        return _FakeStream(_answer(), ["Net ", "cevap."])


# --- (b) per-call fallback: a "new SDK" (create/stream accept **kwargs, so the
#     guard says capable and thinking IS added) that fails *because of* thinking
#     and succeeds once thinking is stripped.
class _ThinkingFailsMessages:
    def __init__(self, error_factory):
        self._error_factory = error_factory
        self.kw_log = []

    def create(self, **kw):
        self.kw_log.append(kw)
        if "thinking" in kw:
            raise self._error_factory()
        return _answer()

    def stream(self, **kw):
        self.kw_log.append(kw)
        if "thinking" in kw:
            raise self._error_factory()
        return _FakeStream(_answer(), ["Net ", "cevap."])


class _Client:
    def __init__(self, messages):
        self.messages = messages


def _patch(monkeypatch, messages):
    monkeypatch.setattr(ai_service, "_client", lambda: _Client(messages))


@pytest.fixture(autouse=True)
def _clear_guard_cache():
    """The capability guard is lru_cached by the create-fn identity; clear it
    around each test so a fake's verdict never leaks into another test."""
    agent_service._create_accepts_thinking.cache_clear()
    yield
    agent_service._create_accepts_thinking.cache_clear()


# --------------------------------------------------------------------------- #
# Unit: the guard's verdict per signature shape
# --------------------------------------------------------------------------- #
def test_guard_detects_thinking_support_by_signature():
    def old(self, *, model, max_tokens, messages):  # pre-0.45 SDK shape
        ...

    def new(self, *, model, max_tokens, messages, thinking=None):  # ≥0.45
        ...

    def kwargs(self, **kw):  # **kwargs accepts anything
        ...

    assert agent_service._create_accepts_thinking(old) is False
    assert agent_service._create_accepts_thinking(new) is True
    assert agent_service._create_accepts_thinking(kwargs) is True


# --------------------------------------------------------------------------- #
# (a) Capability guard — flag ON but SDK can't accept thinking
# --------------------------------------------------------------------------- #
def test_capability_guard_disables_thinking_when_sdk_unsupported(
        db, seed, monkeypatch, caplog):
    """Flag ON, but the installed SDK has no `thinking` param: the agent must NOT
    pass thinking on any call (so no TypeError) and must still return an answer —
    and it warns clearly. Covers both the stream and non-stream paths."""
    cid = seed["a"]["company"].id
    monkeypatch.setattr(settings, "ai_agent_thinking_enabled", True)
    old = _OldMessages()
    _patch(monkeypatch, old)

    import logging
    with caplog.at_level(logging.WARNING, logger="yapi.agent"):
        res = agent_service.run_agent(db, cid, [{"role": "user", "content": "x"}])

    assert res["answer_markdown"] == "Net cevap."          # answer, not an outage
    assert old.kw_log, "the model was actually called"
    assert all("thinking" not in kw for kw in old.kw_log)  # guard kept it off
    assert any("does not accept a `thinking`" in r.message for r in caplog.records)


def test_capability_guard_disables_thinking_on_stream_path(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    monkeypatch.setattr(settings, "ai_agent_thinking_enabled", True)
    old = _OldMessages()
    _patch(monkeypatch, old)

    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "x"}]))
    final = events[-1]["data"]
    assert final["answer_markdown"] == "Net cevap."
    assert all("thinking" not in kw for kw in old.kw_log)


# --------------------------------------------------------------------------- #
# (b) Per-call fallback — thinking IS sent, fails because of thinking, retried
# --------------------------------------------------------------------------- #
def _typeerror():
    # Mirrors the real 0.42.0 failure verbatim.
    return TypeError("create() got an unexpected keyword argument 'thinking'")


def _api_thinking_error():
    # Mirrors an API 400 specifically about the thinking parameter.
    return RuntimeError("BadRequestError: thinking.budget_tokens: unsupported")


@pytest.mark.parametrize("error_factory", [_typeerror, _api_thinking_error])
def test_per_call_fallback_retries_without_thinking_nonstream(
        db, seed, monkeypatch, error_factory):
    """thinking is enabled and accepted by the SDK signature, but the call fails
    *because of* thinking. The agent strips thinking and retries once, so the user
    still gets a normal answer rather than the degraded outage message."""
    cid = seed["a"]["company"].id
    monkeypatch.setattr(settings, "ai_agent_thinking_enabled", True)
    msgs = _ThinkingFailsMessages(error_factory)
    _patch(monkeypatch, msgs)

    res = agent_service.run_agent(db, cid, [{"role": "user", "content": "x"}])

    assert res["answer_markdown"] == "Net cevap."       # not the degraded message
    assert res["answer_markdown"] != agent_service.DEGRADED_MESSAGE
    # First attempt carried thinking (and failed); the retry stripped it.
    assert "thinking" in msgs.kw_log[0]
    assert "thinking" not in msgs.kw_log[-1]
    assert len(msgs.kw_log) >= 2


@pytest.mark.parametrize("error_factory", [_typeerror, _api_thinking_error])
def test_per_call_fallback_retries_without_thinking_stream(
        db, seed, monkeypatch, error_factory):
    """The stream path strips thinking and retries the SAME streaming call, so the
    user still gets a streamed answer (delta events present). Parametrized over both
    thinking-error shapes — the unexpected-kwarg TypeError AND an API error that
    merely *mentions* thinking — to match the non-stream coverage (the stream path
    must not silently handle only one shape)."""
    cid = seed["a"]["company"].id
    monkeypatch.setattr(settings, "ai_agent_thinking_enabled", True)
    msgs = _ThinkingFailsMessages(error_factory)
    _patch(monkeypatch, msgs)

    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "x"}]))

    deltas = [e for e in events if e["type"] == "delta"]
    final = events[-1]["data"]
    assert final["answer_markdown"] == "Net cevap."
    assert "".join(d["text"] for d in deltas) == "Net cevap."  # still streamed
    assert "thinking" in msgs.kw_log[0]
    assert "thinking" not in msgs.kw_log[-1]


def test_non_thinking_error_still_degrades(db, seed, monkeypatch):
    """A failure that is NOT about thinking must NOT trigger the strip-and-retry —
    it degrades normally (AIUnavailable -> degraded response), so the fallback is
    targeted, not a blanket retry-everything."""
    cid = seed["a"]["company"].id
    monkeypatch.setattr(settings, "ai_agent_thinking_enabled", True)

    class _AlwaysFails:
        def __init__(self):
            self.kw_log = []

        def create(self, **kw):
            self.kw_log.append(kw)
            raise RuntimeError("503 service unavailable")  # unrelated to thinking

        def stream(self, **kw):
            self.kw_log.append(kw)
            raise RuntimeError("503 service unavailable")

    msgs = _AlwaysFails()
    _patch(monkeypatch, msgs)

    # An unrelated failure degrades the normal way: _create_call raises
    # AIUnavailable (the api layer turns that into the Turkish degraded response).
    with pytest.raises(ai_service.AIUnavailable):
        agent_service.run_agent(db, cid, [{"role": "user", "content": "x"}])
    # No thinking-strip retry: the single create attempt carried thinking and the
    # call degraded immediately (no second thinking-less attempt).
    assert len(msgs.kw_log) == 1
    assert "thinking" in msgs.kw_log[0]


# --------------------------------------------------------------------------- #
# (c) Budget guard — thinking_budget must leave room for the answer within
#     max_tokens. A mis-config (budget >= max_tokens) must SKIP thinking with a
#     warning, never crash and never send an impossible thinking block. (This is
#     the third guard in the thinking block; the (a)/(b) tests above never trip it
#     because the defaults satisfy max_tokens > budget.)
# --------------------------------------------------------------------------- #
def test_budget_guard_skips_thinking_when_budget_exceeds_max_tokens(
        db, seed, monkeypatch, caplog):
    """Flag ON and the SDK accepts thinking, but the budget is mis-configured so it
    would not leave room for the answer (budget >= max_tokens). The agent must NOT
    attach thinking (no crash, no impossible block) and must still answer, warning
    clearly."""
    cid = seed["a"]["company"].id
    monkeypatch.setattr(settings, "ai_agent_thinking_enabled", True)
    # Mis-config: budget equals / exceeds max_tokens -> no room for the answer.
    monkeypatch.setattr(settings, "ai_agent_max_tokens", 2000)
    monkeypatch.setattr(settings, "ai_agent_thinking_budget", 2000)
    msgs = _ThinkingFailsMessages(_typeerror)  # would raise if thinking leaked in
    _patch(monkeypatch, msgs)

    import logging
    with caplog.at_level(logging.WARNING, logger="yapi.agent"):
        res = agent_service.run_agent(db, cid, [{"role": "user", "content": "x"}])

    assert res["answer_markdown"] == "Net cevap."          # answered, no crash
    assert msgs.kw_log, "the model was actually called"
    assert all("thinking" not in kw for kw in msgs.kw_log)  # budget guard kept it off
    assert any("leave room for the answer" in r.message for r in caplog.records)


def test_budget_guard_skips_thinking_on_stream_path(db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    monkeypatch.setattr(settings, "ai_agent_thinking_enabled", True)
    # budget > max_tokens (strictly) is also a mis-config: only max>budget enables.
    monkeypatch.setattr(settings, "ai_agent_max_tokens", 1500)
    monkeypatch.setattr(settings, "ai_agent_thinking_budget", 4000)
    msgs = _ThinkingFailsMessages(_typeerror)
    _patch(monkeypatch, msgs)

    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "x"}]))
    final = events[-1]["data"]
    assert final["answer_markdown"] == "Net cevap."
    assert all("thinking" not in kw for kw in msgs.kw_log)


# --------------------------------------------------------------------------- #
# (d) Mid-stream thinking failure — the stream emits some text deltas and THEN
#     fails *because of* thinking. The plain stream-fallback test can't catch this
#     (its fake raises on .stream() entry, before any delta is yielded).
#
#     A naive strip-and-re-stream would RE-yield the whole answer and the user
#     would see the pre-failure prefix doubled ("Net Net cevap."). _stream_call
#     guards against that: once any delta has been emitted, it recovers via a
#     single NON-stream call instead of re-streaming, so the prefix is never
#     duplicated. (When nothing has streamed yet — the common case, since a
#     thinking error usually surfaces at request init — it re-streams cleanly;
#     that path is covered by test_per_call_fallback_retries_without_thinking_stream.)
# --------------------------------------------------------------------------- #
class _MidStreamFailsMessages:
    """A 'new SDK': stream yields one delta and THEN raises a thinking error while
    thinking is present; the retry (thinking stripped) streams the full answer."""
    def __init__(self):
        self.kw_log = []

    def create(self, **kw):  # present so capability guard reads **kwargs == capable
        self.kw_log.append(kw)
        return _answer()

    def stream(self, **kw):
        self.kw_log.append(kw)
        fail = "thinking" in kw

        class _S:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            @property
            def text_stream(self_inner):
                def gen():
                    yield "Net "
                    if fail:
                        raise TypeError(
                            "create() got an unexpected keyword argument 'thinking'")
                    yield "cevap."
                return gen()

            def get_final_message(self_inner):
                return _answer()

        return _S()


def test_mid_stream_thinking_failure_recovers_without_double_emit(
        db, seed, monkeypatch):
    cid = seed["a"]["company"].id
    monkeypatch.setattr(settings, "ai_agent_thinking_enabled", True)
    msgs = _MidStreamFailsMessages()
    _patch(monkeypatch, msgs)

    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "x"}]))

    deltas = [e["text"] for e in events if e["type"] == "delta"]
    final = events[-1]["data"]

    # The turn RECOVERS (no outage) and the final answer is correct.
    assert final["answer_markdown"] == "Net cevap."
    assert final["answer_markdown"] != agent_service.DEGRADED_MESSAGE
    # First attempt streamed with thinking and failed mid-stream; recovery dropped
    # to a non-stream call with thinking stripped.
    assert "thinking" in msgs.kw_log[0]
    assert "thinking" not in msgs.kw_log[-1]
    # The pre-failure prefix is emitted exactly ONCE — recovery via non-stream
    # means no re-streamed duplicate. (Only the "Net " prefix streamed before the
    # failure; the final text comes from the non-stream Message.)
    assert "".join(deltas) == "Net ", (
        "the pre-failure prefix must not be duplicated; got " + repr("".join(deltas))
    )
