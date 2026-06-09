"""CR-003-H: natural-language AI assistant."""
from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])


def test_assistant_all_projects(client, seed):
    _login(client, seed)
    r = client.post("/api/v1/ai/assistant", json={"question": "Hangi proje en fazla risk taşıyor?"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "answer" in data and data["answer"]
    assert "generated_at" in data
    # Context includes the portfolio when no project filter is set.
    assert "projeler" in data["data_points"]


def test_assistant_project_scoped(client, seed):
    _login(client, seed)
    pid = seed["a"]["project"].id
    r = client.post("/api/v1/ai/assistant", json={"question": "Bu projenin marjı nedir?", "project_id": str(pid)})
    assert r.status_code == 200, r.text
    assert "proje" in r.json()["data"]["data_points"]


def test_assistant_cross_company_project_rejected(client, seed):
    _login(client, seed)
    other = seed["b"]["project"].id
    r = client.post("/api/v1/ai/assistant", json={"question": "x", "project_id": str(other)})
    assert r.status_code == 404  # RLS/scoping prevents cross-company access
