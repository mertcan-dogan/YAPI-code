"""CR-044 — Skills (Beceriler): the AI-generated report-file loop.

Runs on the SQLite ``client`` + two-company ``seed`` fixtures (conftest), like the
other studio suites. Proves the CR-044 invariants:

* ``propose_skill`` DRAFTS a skill — validated plan, NO DB write (no Skill /
  SkillRun / ApprovalRequest), no ``request_id`` (draft card, not an approval);
  an invalid plan raises ``ActionError`` and yields no draft.
* ``POST /skills`` creates a skill OWNED by the caller (company_id/owner_id from
  auth, never the body) and re-validates the plan server-side.
* ``POST /skills/{id}/run`` (and the ``run_skill`` agent tool) is READ-ONLY: it
  runs the plan through the trusted engine (``run_spec``), stores a file, writes ONE
  ``SkillRun`` row, returns a short-lived signed URL — and writes ZERO business rows
  and ZERO approval requests.
* NO FABRICATION: the figures in the file come ONLY from ``run_spec`` — the bytes
  handed to the exporter equal a direct ``run_spec`` call on the plan's widgets.
* Multi-tenant isolation: cross-company GET / run / re-download → 404; the signed-URL
  helper refuses to sign a path outside the caller's company folder.

The ``@pytest.mark.pg`` WITH-CHECK tenant-isolation proof for ``skills`` /
``skill_runs`` lives in ``test_rls_isolation_pg.py`` (env-gated; skips on SQLite).
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR, ROLE_FINANCE
from app.models.approval_request import ApprovalRequest
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.skill import Skill, SkillRun
from app.responses import APIError
from app.services import agent as agent_service
from app.services import agent_actions as actions
from app.services import skills as skills_service
from app.services import storage
from app.services.studio.engine import run_spec

D = Decimal
BASE = "/api/v1/skills"

SPEC_KPI = {"metrics": ["cost_try"], "viz": "kpi"}
SPEC_TABLE = {"metrics": ["cost_try"], "dimensions": ["project"], "viz": "table"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ids(seed, label="a"):
    # third element is the Project OBJECT (used by _cost for id + company_id).
    return (seed[label]["company"].id,
            seed[label]["users"][ROLE_DIRECTOR].id,
            seed[label]["project"])


def _layout(x=0, y=0, w=6, h=4):
    return {"x": x, "y": y, "w": w, "h": h}


def _kpi(wid="w1", *, spec=None, title="Maliyet"):
    return {"id": wid, "type": "kpi", "title": title, "layout": _layout(), "spec": spec or dict(SPEC_KPI)}


def _plan(widgets=None, *, fmt="xlsx", title="Aylık Maliyet Özeti", date_range=None):
    return {"format": fmt, "title": title, "widgets": widgets or [_kpi()], "date_range": date_range}


def _cost(db, p, amount, uid, d=date(2026, 1, 10), cat="material_steel"):
    amt = D(str(amount))
    db.add(CostEntry(
        project_id=p.id, company_id=p.company_id, entry_date=d, cost_category=cat,
        amount_try=amt, vat_amount_try=D("0"), total_with_vat_try=amt,
        payment_status="unpaid", entry_type="actual", created_by=uid,
    ))
    db.commit()


def _counts(db):
    return {
        "costs": db.execute(select(func.count()).select_from(CostEntry)).scalar(),
        "invoices": db.execute(select(func.count()).select_from(ClientInvoice)).scalar(),
        "skills": db.execute(select(func.count()).select_from(Skill)).scalar(),
        "skill_runs": db.execute(select(func.count()).select_from(SkillRun)).scalar(),
        "approvals": db.execute(select(func.count()).select_from(ApprovalRequest)).scalar(),
    }


def _mock_storage(monkeypatch):
    """No real Supabase calls in tests: capture uploads + hand back a fake URL."""
    captured = {}
    monkeypatch.setattr(storage, "upload_bytes",
                        lambda path, data, content_type, **k: captured.update(path=path, data=data, ct=content_type))
    monkeypatch.setattr(storage, "signed_url",
                        lambda path, *, company_id, **k: f"https://signed.example/{path}?token=abc")
    return captured


def _make_skill(db, cid, uid, *, name="Maliyet Becerisi", plan=None, fmt="xlsx", visibility="private"):
    s = Skill(company_id=cid, owner_id=uid, created_by=uid, name=name,
              instruction="her ay maliyet özeti", plan=plan or _plan(fmt=fmt),
              format=fmt, visibility=visibility)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# --------------------------------------------------------------------------- #
# 1. propose_skill — DRAFT only, zero writes; invalid → ActionError
# --------------------------------------------------------------------------- #
def test_propose_skill_returns_draft_and_writes_nothing(db, seed):
    cid, uid, _ = _ids(seed)
    before = _counts(db)
    r = actions.propose_skill(
        db, cid, uid, name="Aylık Maliyet", widgets=[_kpi()], format="xlsx",
        instruction="Her ay maliyet özeti; Excel.",
    )
    assert r["status"] == "draft"
    pa = r["proposed_action"]
    assert pa["kind"] == "draft_skill"
    assert "request_id" not in pa              # a DRAFT, not an approval
    assert pa["format"] == "xlsx"
    assert pa["instruction"] == "Her ay maliyet özeti; Excel."
    # The compiled, runnable plan rode along (dashboard-shaped).
    assert pa["plan"]["format"] == "xlsx"
    assert pa["plan"]["widgets"] and pa["plan"]["widgets"][0]["spec"]["metrics"] == ["cost_try"]
    # NOTHING was written.
    assert _counts(db) == before


def test_propose_skill_rejects_invalid_plan(db, seed):
    cid, uid, _ = _ids(seed)
    before = _counts(db)
    with pytest.raises(actions.ActionError):
        actions.propose_skill(db, cid, uid, name="Kötü",
                              widgets=[_kpi(spec={"metrics": ["uydurma_metrik"], "viz": "kpi"})])
    with pytest.raises(actions.ActionError):
        actions.propose_skill(db, cid, uid, name="Boş", widgets=[])
    assert _counts(db) == before


def test_propose_skill_is_in_action_names_run_skill_is_not(db):
    # propose_skill is a DRAFT action tool; run_skill is a read-only special tool
    # (kept out of both registries, like create_chart) — the CR-011 invariant holds.
    assert "propose_skill" in agent_service.ACTION_TOOL_NAMES
    assert "run_skill" not in agent_service.ACTION_TOOL_NAMES
    assert agent_service.ACTION_TOOL_NAMES.isdisjoint(set(agent_service.TOOL_REGISTRY))


# --------------------------------------------------------------------------- #
# 2. POST /skills — the user's own create (owner = caller); re-validates plan
# --------------------------------------------------------------------------- #
def test_create_skill_owner_is_caller(client, seed):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    resp = client.post(BASE, json={
        "name": "Aylık Maliyet", "instruction": "Her ay maliyet özeti",
        "plan": _plan(), "format": "xlsx", "visibility": "private",
    })
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["owner_id"] == str(director.id)
    assert data["is_owner"] is True
    assert data["format"] == "xlsx"


def test_create_skill_revalidates_plan_server_side(client, seed):
    client.login(seed["a"]["users"][ROLE_FINANCE])
    resp = client.post(BASE, json={
        "name": "Kötü", "instruction": "x",
        "plan": _plan(widgets=[_kpi(spec={"metrics": ["uydurma"], "viz": "kpi"})]),
        "format": "xlsx",
    })
    assert resp.status_code == 422


def test_create_skill_rejects_bad_format(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    resp = client.post(BASE, json={
        "name": "X", "instruction": "x", "plan": _plan(), "format": "csv",
    })
    assert resp.status_code == 422  # Literal["xlsx","pdf"] guard


# --------------------------------------------------------------------------- #
# 3. RUN — read-only file generation; SkillRun row; signed URL; NO FABRICATION
# --------------------------------------------------------------------------- #
def test_run_skill_writes_run_stores_file_and_returns_signed_url(client, db, seed, monkeypatch):
    cid, uid, project = _ids(seed)
    _cost(db, project, 125_000, uid)             # live data the file must reflect
    captured = _mock_storage(monkeypatch)

    director = seed["a"]["users"][ROLE_DIRECTOR]
    skill = _make_skill(db, cid, uid)
    before = _counts(db)

    client.login(director)
    resp = client.post(f"{BASE}/{skill.id}/run")
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["run_id"] and body["format"] == "xlsx"
    assert body["file_name"].endswith(".xlsx")
    assert body["download_url"].startswith("https://signed.example/")

    # Exactly ONE SkillRun(ok); ZERO business rows; ZERO approvals.
    after = _counts(db)
    assert after["skill_runs"] == before["skill_runs"] + 1
    assert after["costs"] == before["costs"]
    assert after["invoices"] == before["invoices"]
    assert after["approvals"] == before["approvals"]

    run = db.execute(select(SkillRun).where(SkillRun.skill_id == skill.id)).scalar_one()
    assert run.status == "ok"
    assert run.file_path.startswith(f"{cid}/skills/{skill.id}/")
    assert run.run_by == uid

    # A real, non-empty file was stored.
    assert captured["data"] and len(captured["data"]) > 0


def test_run_skill_file_figures_come_only_from_run_spec(client, db, seed, monkeypatch):
    """NO FABRICATION: the results handed to the exporter equal a direct run_spec
    call on the plan's widget — the file is built by the engine, never the model."""
    cid, uid, project = _ids(seed)
    _cost(db, project, 99_000, uid)
    _mock_storage(monkeypatch)

    # Spy on the exporter to capture the per-widget results, delegating to the real
    # exporter so real bytes are still produced + stored.
    from app.services.studio.export import studio_export_dashboard as real_export
    seen = {}

    def spy_export(widgets, results, title, fmt):
        seen["results"] = results
        return real_export(widgets, results, title, fmt)

    monkeypatch.setattr(skills_service, "studio_export_dashboard", spy_export)

    skill = _make_skill(db, cid, uid, plan=_plan(widgets=[_kpi("w1")]))
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    resp = client.post(f"{BASE}/{skill.id}/run")
    assert resp.status_code == 200, resp.text

    # The exporter received exactly what the engine computed for the widget spec.
    direct = run_spec(db, cid, dict(SPEC_KPI))
    assert seen["results"]["w1"] == direct


def test_run_skill_cross_company_404(client, db, seed, monkeypatch):
    cid_a, uid_a, _ = _ids(seed, "a")
    _mock_storage(monkeypatch)
    skill = _make_skill(db, cid_a, uid_a)               # owned by company A
    client.login(seed["b"]["users"][ROLE_DIRECTOR])     # company B
    assert client.post(f"{BASE}/{skill.id}/run").status_code == 404
    assert client.get(f"{BASE}/{skill.id}").status_code == 404


def test_run_skill_agent_tool_is_read_only_no_approval(db, seed, monkeypatch):
    cid, uid, project = _ids(seed)
    _cost(db, project, 50_000, uid)
    _mock_storage(monkeypatch)
    skill = _make_skill(db, cid, uid)
    before = _counts(db)

    result = skills_service.run_skill_tool(db, cid, uid, str(skill.id))
    assert result["ok"] is True
    pa = result["proposed_action"]
    assert pa["kind"] == "run_result"
    assert pa["download_url"].startswith("https://signed.example/")
    assert pa["skill_name"] == skill.name

    after = _counts(db)
    assert after["skill_runs"] == before["skill_runs"] + 1   # one run row
    assert after["approvals"] == before["approvals"]          # NO approval created
    assert after["costs"] == before["costs"]


def test_run_skill_agent_tool_bad_id_returns_error(db, seed, monkeypatch):
    cid, uid, _ = _ids(seed)
    _mock_storage(monkeypatch)
    # cross-company skill id is simply not viewable → clean error, no raise.
    other = _make_skill(db, seed["b"]["company"].id, seed["b"]["users"][ROLE_DIRECTOR].id)
    out = skills_service.run_skill_tool(db, cid, uid, str(other.id))
    assert "error" in out


# --------------------------------------------------------------------------- #
# 4. CRUD + runs history + re-download scoping
# --------------------------------------------------------------------------- #
def test_skill_crud_and_runs_history(client, db, seed, monkeypatch):
    cid, uid, project = _ids(seed)
    _cost(db, project, 10_000, uid)
    _mock_storage(monkeypatch)
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)

    created = client.post(BASE, json={
        "name": "Beceri", "instruction": "x", "plan": _plan(), "format": "xlsx",
    }).json()["data"]
    sid = created["id"]

    # list shows it
    rows = client.get(BASE).json()["data"]
    assert any(r["id"] == sid for r in rows)

    # run → appears in history with last_run_at populated on the list
    client.post(f"{BASE}/{sid}/run")
    runs = client.get(f"{BASE}/{sid}/runs").json()["data"]
    assert len(runs) == 1 and runs[0]["status"] == "ok"
    listed = next(r for r in client.get(BASE).json()["data"] if r["id"] == sid)
    assert listed["last_run_at"] is not None

    # update (PUT) — recompiled plan / rename
    upd = client.put(f"{BASE}/{sid}", json={"name": "Yeni Ad"})
    assert upd.status_code == 200 and upd.json()["data"]["name"] == "Yeni Ad"

    # soft delete → 404 afterwards + absent from list
    assert client.delete(f"{BASE}/{sid}").status_code == 200
    assert client.get(f"{BASE}/{sid}").status_code == 404
    assert all(r["id"] != sid for r in client.get(BASE).json()["data"])


def test_redownload_is_company_scoped(client, db, seed, monkeypatch):
    cid_a, uid_a, project = _ids(seed, "a")
    _cost(db, project, 20_000, uid_a)
    _mock_storage(monkeypatch)
    skill = _make_skill(db, cid_a, uid_a)

    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    run_id = client.post(f"{BASE}/{skill.id}/run").json()["data"]["run_id"]

    # owner can re-download
    ok = client.post(f"{BASE}/runs/{run_id}/download")
    assert ok.status_code == 200 and ok.json()["data"]["download_url"].startswith("https://signed.example/")

    # company B cannot re-download company A's run file
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.post(f"{BASE}/runs/{run_id}/download").status_code == 404


def test_private_skill_not_visible_to_company_stranger(client, db, seed):
    cid, owner_uid, _ = _ids(seed)
    # a private skill owned by the director
    skill = _make_skill(db, cid, owner_uid, visibility="private")
    # a different same-company user (finance) cannot see it
    client.login(seed["a"]["users"][ROLE_FINANCE])
    assert client.get(f"{BASE}/{skill.id}").status_code == 404
    # but a company-visible one is visible
    shared = _make_skill(db, cid, owner_uid, name="Paylaşılan", visibility="company")
    assert client.get(f"{BASE}/{shared.id}").status_code == 200


# --------------------------------------------------------------------------- #
# 4b. CR-044.1 — last_run on SkillOut / SkillListItem (findability after reload)
# --------------------------------------------------------------------------- #
def test_skill_last_run_null_then_reflects_latest_run(client, db, seed, monkeypatch):
    cid, uid, project = _ids(seed)
    _cost(db, project, 15_000, uid)
    _mock_storage(monkeypatch)
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)

    sid = client.post(BASE, json={
        "name": "Beceri", "instruction": "x", "plan": _plan(), "format": "xlsx",
    }).json()["data"]["id"]

    # Fresh skill → last_run is null on both detail and list.
    assert client.get(f"{BASE}/{sid}").json()["data"]["last_run"] is None
    listed = next(r for r in client.get(BASE).json()["data"] if r["id"] == sid)
    assert listed["last_run"] is None and listed["last_run_at"] is None

    # Run it → last_run reflects the latest ok run (run_id + file_name + status).
    run = client.post(f"{BASE}/{sid}/run").json()["data"]
    detail = client.get(f"{BASE}/{sid}").json()["data"]
    assert detail["last_run"] is not None
    assert detail["last_run"]["run_id"] == run["run_id"]
    assert detail["last_run"]["status"] == "ok"
    assert detail["last_run"]["file_name"] == run["file_name"]

    # The list row carries the same last_run for an immediate re-download on load.
    listed2 = next(r for r in client.get(BASE).json()["data"] if r["id"] == sid)
    assert listed2["last_run"]["run_id"] == run["run_id"]
    assert listed2["last_run_at"] is not None


# --------------------------------------------------------------------------- #
# 5. signed-URL helper — scope check (shared infra for CR-045 + future exports)
# --------------------------------------------------------------------------- #
def test_signed_url_refuses_foreign_path(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "supabase_url", "https://x.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "k")
    cid = uuid.uuid4()
    with pytest.raises(APIError) as ei:
        storage.signed_url(f"{uuid.uuid4()}/skills/a.xlsx", company_id=cid)
    assert ei.value.status_code == 422
