"""CR-011-A — token streaming on /ai/agent (§1.1).

The agent loop is reused unchanged; streaming only adds live ``delta`` text events
and real-time ``step`` events, then finalizes with the SAME structured payload
(charts/citations/log) the non-stream path returns. On a streaming error it falls
back to a non-stream call so the answer is never lost.
"""
from datetime import date
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.services import agent as agent_service
from app.services import ai as ai_service


# --------------------------------------------------------------------------- #
# Fake streaming Anthropic client
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


class _FakeStream:
    """Mimics anthropic's MessageStream context manager."""

    def __init__(self, resp, chunks, fail=False):
        self._resp = resp
        self._chunks = chunks
        self._fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        if self._fail:
            raise RuntimeError("stream broke mid-flight")
        return iter(self._chunks)

    def get_final_message(self):
        return self._resp


class _Messages:
    def __init__(self, responder):
        self._responder = responder
        self.calls = 0
        self.stream_calls = 0
        self.create_calls = 0

    def stream(self, **kw):
        self.stream_calls += 1
        resp, chunks, fail = self._responder(self.calls, kw)
        self.calls += 1
        return _FakeStream(resp, chunks, fail)

    def create(self, **kw):
        # Used by the non-stream path AND the streaming fallback.
        self.create_calls += 1
        resp, _chunks, _fail = self._responder(self.calls, kw)
        self.calls += 1
        return resp


class _Client:
    def __init__(self, responder):
        self.messages = _Messages(responder)


def _patch(monkeypatch, responder):
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


_ANSWER = "Akçansa ile toplam **4.500 ₺** harcandı."
_ANSWER_CHUNKS = ["Akçansa ile ", "toplam **4.500 ₺** ", "harcandı."]


def _vendor_then_answer(call, kw):
    """call 0: tool_use get_vendor_spend (no preamble text);
    call 1: end_turn answer streamed in 3 chunks."""
    if call == 0:
        return _Resp("tool_use", [_tool("get_vendor_spend", {"vendor_name": "Akçansa"}, "t0")]), [], False
    return _Resp("end_turn", [_text(_ANSWER)]), _ANSWER_CHUNKS, False


# --------------------------------------------------------------------------- #
# run_agent_stream — event sequence
# --------------------------------------------------------------------------- #
def test_stream_yields_deltas_steps_then_final(db, seed, monkeypatch):
    cid = _seed_vendor_costs(db, seed)
    _patch(monkeypatch, _vendor_then_answer)

    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "Akçansa ne kadar?"}],
    ))

    kinds = [e["type"] for e in events]
    # Exactly one final, and it is last.
    assert kinds[-1] == "final"
    assert kinds.count("final") == 1
    # A step event fired for the tool call.
    steps = [e for e in events if e["type"] == "step"]
    assert [s["tool"] for s in steps] == ["get_vendor_spend"]
    assert steps[0]["label"]  # Turkish label present
    # Live token deltas concatenate to the final answer text.
    streamed = "".join(e["text"] for e in events if e["type"] == "delta")
    assert streamed.strip() == _ANSWER
    final = events[-1]["data"]
    assert final["answer_markdown"] == _ANSWER
    assert final["tools_used"] == ["get_vendor_spend"]
    # Streaming did not drop citations / charts / generated_at (§7).
    assert len(final["citations"]) >= 1
    assert all("highlight=" in c["deep_link"] for c in final["citations"])
    assert "generated_at" in final


def test_stream_final_payload_matches_non_stream(db, seed, monkeypatch):
    cid = _seed_vendor_costs(db, seed)
    _patch(monkeypatch, _vendor_then_answer)
    streamed = [e for e in agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "Akçansa ne kadar?"}])]
    stream_final = streamed[-1]["data"]

    _patch(monkeypatch, _vendor_then_answer)
    non_stream = agent_service.run_agent(db, cid, [{"role": "user", "content": "Akçansa ne kadar?"}])

    # The structured payload is identical apart from the timestamp.
    for k in ("answer_markdown", "tools_used", "row_counts"):
        assert stream_final[k] == non_stream[k]
    assert len(stream_final["citations"]) == len(non_stream["citations"])
    assert len(stream_final["charts"]) == len(non_stream["charts"])


def test_stream_logs_one_query_row_at_stream_end(db, seed, monkeypatch):
    from sqlalchemy import select
    from app.models.ai_query_log import AIQueryLog

    cid = _seed_vendor_costs(db, seed)
    uid = seed["a"]["users"][ROLE_DIRECTOR].id
    _patch(monkeypatch, _vendor_then_answer)

    list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "Akçansa ne kadar?"}], user_id=uid))

    rows = db.execute(select(AIQueryLog).where(AIQueryLog.company_id == cid)).scalars().all()
    assert len(rows) == 1
    assert rows[0].tools_used == ["get_vendor_spend"]


# --------------------------------------------------------------------------- #
# Fallback: streaming error -> non-stream, answer preserved (§1.1 / §7)
# --------------------------------------------------------------------------- #
def test_stream_falls_back_to_non_stream_on_error(db, seed, monkeypatch):
    cid = seed["a"]["company"].id

    def responder(call, kw):
        # The streaming read fails; the loop must fall back to a create() call,
        # which returns the answer.
        return _Resp("end_turn", [_text("Yanıt yine de geldi.")]), ["hiç"], True

    client = _patch(monkeypatch, responder)
    events = list(agent_service.run_agent_stream(
        db, cid, [{"role": "user", "content": "x"}]))

    final = events[-1]
    assert final["type"] == "final"
    assert final["data"]["answer_markdown"] == "Yanıt yine de geldi."
    # Fell back: a create() call was made after the failed stream.
    assert client.messages.create_calls == 1


# --------------------------------------------------------------------------- #
# sse_event serialization
# --------------------------------------------------------------------------- #
def test_sse_event_frames():
    d = agent_service.sse_event({"type": "delta", "text": "merhaba"})
    assert d.startswith("event: delta\n")
    assert '"text": "merhaba"' in d
    assert d.endswith("\n\n")

    s = agent_service.sse_event({"type": "step", "tool": "get_cashflow", "label": "Nakit akışı hesaplanıyor…"})
    assert "event: step\n" in s
    assert "get_cashflow" in s

    f = agent_service.sse_event({"type": "final", "data": {"answer_markdown": "ok"}})
    assert "event: final\n" in f
    assert '"answer_markdown": "ok"' in f


# --------------------------------------------------------------------------- #
# Endpoint: ?stream=1 returns an SSE stream
# --------------------------------------------------------------------------- #
def _parse_sse(text):
    """Parse an SSE body into a list of (event, data_str)."""
    out = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        out.append((ev, data))
    return out


def test_endpoint_stream_returns_event_stream(client, seed, monkeypatch):
    import json as _json

    _patch(monkeypatch, _vendor_then_answer)
    client.login(seed["a"]["users"][ROLE_DIRECTOR])

    r = client.post("/api/v1/ai/agent?stream=1",
                    json={"messages": [{"role": "user", "content": "Akçansa ne kadar?"}]})
    assert r.status_code == 200, r.text
    assert "text/event-stream" in r.headers["content-type"]

    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert "delta" in kinds
    assert kinds[-1] == "final"
    final_data = _json.loads([d for e, d in events if e == "final"][-1])
    assert final_data["answer_markdown"] == _ANSWER
    assert final_data["tools_used"] == ["get_vendor_spend"]


def test_endpoint_stream_degrades_without_api_key(client, seed, monkeypatch):
    import json as _json
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/ai/agent?stream=1",
                    json={"messages": [{"role": "user", "content": "merhaba"}]})
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    assert events[-1][0] == "final"
    final_data = _json.loads(events[-1][1])
    assert final_data["answer_markdown"] == agent_service.DEGRADED_MESSAGE


def test_endpoint_non_stream_still_json(client, seed, monkeypatch):
    """Default (no ?stream) keeps the JSON envelope unchanged."""
    _patch(monkeypatch, _vendor_then_answer)
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/ai/agent",
                    json={"messages": [{"role": "user", "content": "Akçansa ne kadar?"}]})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    data = r.json()["data"]
    assert data["answer_markdown"] == _ANSWER
