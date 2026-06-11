"""CR-005-G: AI summary caching.

The cache itself lives in a persisted Zustand store on the frontend (run-once per
page, refresh button, per-project key). These tests pin the backend contract the
cache wraps: each AI summary endpoint returns content + a timestamp the store can
key and stamp ("Son güncelleme: …").
"""
from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def test_project_narrative_returns_content_and_timestamp(client, seed):
    """Source for the 'project-summary-{id}' cache entry."""
    pid = _login(client, seed)
    r = client.post(f"/api/v1/projects/{pid}/ai-narrative")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["narrative"]            # cache content
    assert "generated_at" in data       # cache timestamp


def test_daily_briefing_returns_list(client, seed):
    """Source for the 'dashboard-summary' cache entry (JSON-serialised list)."""
    _login(client, seed)
    r = client.get("/api/v1/ai/daily-briefing")
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["data"], list)


def test_summary_endpoints_are_stable_across_calls(client, seed):
    """Without a refresh the content shape is stable, so caching is safe."""
    pid = _login(client, seed)
    a = client.post(f"/api/v1/projects/{pid}/ai-narrative").json()["data"]
    b = client.post(f"/api/v1/projects/{pid}/ai-narrative").json()["data"]
    assert set(a.keys()) == set(b.keys())
