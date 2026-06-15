"""Fix — charts + citations on saved AI Asistan messages survive PUT -> GET.

Before the fix the conversation Message model only allowed role/text/at, so a
reloaded conversation lost its chart and citation chips. messages is JSONB, so
no migration is needed — the model just has to accept (and validate) the fields.
"""
import uuid

from app.constants import ROLE_DIRECTOR, ROLE_FINANCE

CHART = {
    "chart_type": "line",
    "title": "Bozkurt Aylık",
    "x_key": "month",
    "series": [{"key": "total", "label": "Toplam", "type": "line"}],
    "data": [{"month": "2026-01", "total": 1000}, {"month": "2026-02", "total": 500}],
    "currency": "TRY",
    "source_note": "Kaynak: maliyet kayıtları",
}
CITATIONS = [{"type": "cost_entry", "id": "c1", "label": "Bozkurt · 15.01.2026 — 1.000 ₺",
              "deep_link": "/projects/p/dashboard?highlight=c1"}]


def _conv_body():
    return {
        "title": "Bozkurt analizi",
        "messages": [
            {"role": "user", "text": "Bozkurt ile son 6 ayda ne kadar iş yaptık?"},
            {"role": "ai", "text": "Toplam **1.500 ₺**.", "charts": [CHART], "citations": CITATIONS},
        ],
    }


def test_charts_and_citations_round_trip(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    cid = str(uuid.uuid4())

    r = client.put(f"/api/v1/ai/conversations/{cid}", json=_conv_body())
    assert r.status_code == 200, r.text

    rows = client.get("/api/v1/ai/conversations").json()["data"]
    conv = next(c for c in rows if c["id"] == cid)
    ai_msg = conv["messages"][1]
    assert ai_msg["role"] == "ai"
    # Chart round-trips (normalised via ChartSpec — colours filled in).
    assert len(ai_msg["charts"]) == 1
    chart = ai_msg["charts"][0]
    assert chart["chart_type"] == "line"
    assert chart["series"][0]["color"]          # ChartSpec filled the palette colour
    assert len(chart["data"]) == 2
    # Citations round-trip intact.
    assert ai_msg["citations"] == CITATIONS


def test_user_message_without_extras_stays_clean(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    cid = str(uuid.uuid4())
    client.put(f"/api/v1/ai/conversations/{cid}", json=_conv_body())
    conv = next(c for c in client.get("/api/v1/ai/conversations").json()["data"] if c["id"] == cid)
    user_msg = conv["messages"][0]
    # exclude_none keeps user messages free of null charts/citations keys.
    assert "charts" not in user_msg
    assert "citations" not in user_msg


def test_invalid_chart_spec_rejected(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    cid = str(uuid.uuid4())
    bad = _conv_body()
    bad["messages"][1]["charts"] = [{**CHART, "data": []}]  # empty data fails CR-007-C
    r = client.put(f"/api/v1/ai/conversations/{cid}", json=bad)
    assert r.status_code == 422


def test_persisted_charts_isolated_per_user(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    cid = str(uuid.uuid4())
    client.put(f"/api/v1/ai/conversations/{cid}", json=_conv_body())
    # A different user can't see the conversation (existing per-user scoping holds).
    client.login(seed["a"]["users"][ROLE_FINANCE])
    assert cid not in [c["id"] for c in client.get("/api/v1/ai/conversations").json()["data"]]
