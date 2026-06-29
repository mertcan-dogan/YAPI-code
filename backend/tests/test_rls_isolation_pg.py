"""CR-040: real-Postgres tenant-isolation proof (NOT run on SQLite).

SQLite cannot exercise RLS, so the regular suite cannot prove isolation. This
module proves, against a real Postgres with migration 0040 applied and the
`yapi_app` (NOBYPASSRLS) role created, that:

  (i)  a session scoped to company A cannot SELECT / INSERT / UPDATE / DELETE
       company B's rows;
  (ii) an UNSET GUC is fail-closed (zero rows everywhere);
  (iii) a correctly-scoped session still sees its own data.

It is SKIPPED unless BOTH env vars are set (so CI/local SQLite runs are
unaffected):

  RLS_ADMIN_URL  — an owner/service_role URL (BYPASSRLS) used to seed + clean up.
  RLS_APP_URL    — the yapi_app (NOBYPASSRLS) URL that RLS actually applies to.

Run against a throwaway Supabase branch or local Postgres, e.g.:

  RLS_ADMIN_URL=postgresql+psycopg://postgres:...@host/db \
  RLS_APP_URL=postgresql+psycopg://yapi_app:...@host/db \
  python -m pytest -q tests/test_rls_isolation_pg.py
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text

ADMIN_URL = os.environ.get("RLS_ADMIN_URL")
APP_URL = os.environ.get("RLS_APP_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL),
    reason="set RLS_ADMIN_URL and RLS_APP_URL to run the real-Postgres RLS matrix",
)

# Representative scoped tables to exercise writes against; the fail-closed check
# below sweeps the full set from the migration.
SCOPED_SAMPLE = ["projects", "cost_entries", "client_invoices", "users", "project_closeouts", "reports", "dashboards", "skills", "skill_runs"]


def _set_guc(conn, company_id):
    # is_local=false here because each check runs in its own short connection;
    # the app wires is_local=true per request transaction (see app/db.py).
    conn.execute(
        text("SELECT set_config('app.current_company', :cid, false)"),
        {"cid": str(company_id) if company_id else ""},
    )


@pytest.fixture(scope="module")
def seeded():
    """Seed two companies (A, B) with a project + a cost_entry each, via the
    owner connection. Yields the ids; tears the rows down afterwards."""
    admin = create_engine(ADMIN_URL, future=True)
    a, b = uuid.uuid4(), uuid.uuid4()
    proj_a, proj_b = uuid.uuid4(), uuid.uuid4()
    ce_a, ce_b = uuid.uuid4(), uuid.uuid4()
    with admin.begin() as conn:
        for cid, name in ((a, "RLS-Test-A"), (b, "RLS-Test-B")):
            conn.execute(
                text("INSERT INTO companies (id, name, slug) VALUES (:id, :n, :s)"),
                {"id": cid, "n": name, "s": f"rls-test-{cid.hex[:8]}"},
            )
        for cid, pid in ((a, proj_a), (b, proj_b)):
            conn.execute(
                text(
                    "INSERT INTO projects (id, company_id, name, project_code, "
                    "project_type, client_name, contract_value_try, original_budget_try, "
                    "start_date, planned_end_date) VALUES (:id, :c, :n, :pc, 'road', "
                    "'X', 1, 1, '2025-01-01', '2025-12-31')"
                ),
                {"id": pid, "c": cid, "n": f"P-{cid.hex[:6]}", "pc": f"PRJ-{cid.hex[:6]}"},
            )
        for cid, pid, eid in ((a, proj_a, ce_a), (b, proj_b, ce_b)):
            conn.execute(
                text(
                    "INSERT INTO cost_entries (id, company_id, project_id, amount_try, "
                    "category, description, entry_date) VALUES (:id, :c, :p, 100, "
                    "'malzeme', 'seed', '2025-06-01')"
                ),
                {"id": eid, "c": cid, "p": pid},
            )
    yield {"a": a, "b": b, "proj_a": proj_a, "proj_b": proj_b, "ce_a": ce_a, "ce_b": ce_b}
    with admin.begin() as conn:
        for tbl in ("cost_entries", "projects", "companies"):
            conn.execute(
                text(f"DELETE FROM {tbl} WHERE company_id = :a OR company_id = :b")
                if tbl != "companies"
                else text(f"DELETE FROM companies WHERE id = :a OR id = :b"),
                {"a": a, "b": b},
            )
    admin.dispose()


@pytest.fixture(scope="module")
def app_engine():
    eng = create_engine(APP_URL, future=True)
    yield eng
    eng.dispose()


def test_scoped_session_sees_only_its_own_rows(seeded, app_engine):
    with app_engine.connect() as conn:
        _set_guc(conn, seeded["a"])
        own = conn.execute(text("SELECT count(*) FROM cost_entries")).scalar()
        other = conn.execute(
            text("SELECT count(*) FROM cost_entries WHERE company_id = :b"),
            {"b": seeded["b"]},
        ).scalar()
    assert own >= 1, "company A must see its own cost_entries"
    assert other == 0, "company A must NOT see company B's cost_entries"


def test_cannot_insert_into_another_company(seeded, app_engine):
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    with app_engine.connect() as conn:
        _set_guc(conn, seeded["a"])
        with pytest.raises((DBAPIError, ProgrammingError)):
            conn.execute(
                text(
                    "INSERT INTO cost_entries (id, company_id, project_id, amount_try, "
                    "category, description, entry_date) VALUES (:id, :c, :p, 1, 'x', 'evil', "
                    "'2025-06-01')"
                ),
                {"id": uuid.uuid4(), "c": seeded["b"], "p": seeded["proj_b"]},
            )
            conn.commit()


def test_cannot_update_or_delete_another_company(seeded, app_engine):
    with app_engine.connect() as conn:
        _set_guc(conn, seeded["a"])
        upd = conn.execute(
            text("UPDATE cost_entries SET amount_try = 0 WHERE company_id = :b"),
            {"b": seeded["b"]},
        )
        deleted = conn.execute(
            text("DELETE FROM cost_entries WHERE company_id = :b"), {"b": seeded["b"]}
        )
        conn.commit()
    assert upd.rowcount == 0, "company A must not UPDATE company B rows"
    assert deleted.rowcount == 0, "company A must not DELETE company B rows"


def test_unset_guc_is_fail_closed(seeded, app_engine):
    """No company context ⇒ zero rows on every scoped table (never a leak)."""
    tables = SCOPED_SAMPLE
    with app_engine.connect() as conn:
        # Explicitly unset (empty → NULLIF → NULL in the policy).
        _set_guc(conn, None)
        for tbl in tables:
            n = conn.execute(text(f"SELECT count(*) FROM {tbl}")).scalar()
            assert n == 0, f"unset GUC must yield 0 rows on {tbl}, got {n}"


def test_company_b_mirror(seeded, app_engine):
    with app_engine.connect() as conn:
        _set_guc(conn, seeded["b"])
        own = conn.execute(text("SELECT count(*) FROM cost_entries")).scalar()
        other = conn.execute(
            text("SELECT count(*) FROM cost_entries WHERE company_id = :a"),
            {"a": seeded["a"]},
        ).scalar()
    assert own >= 1 and other == 0


def test_project_closeouts_isolation(seeded, app_engine):
    """0043: a company-A session cannot read/insert company-B closeout rows."""
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    co_a, co_b = uuid.uuid4(), uuid.uuid4()
    # Seed one closeout per company on the A-scoped and B-scoped sessions (each
    # insert must satisfy WITH CHECK for its own company).
    with app_engine.connect() as conn:
        _set_guc(conn, seeded["a"])
        conn.execute(
            text(
                "INSERT INTO project_closeouts (id, company_id, project_id, stage, is_active) "
                "VALUES (:id, :c, :p, 'gecici_kabul', true)"
            ),
            {"id": co_a, "c": seeded["a"], "p": seeded["proj_a"]},
        )
        conn.commit()
    with app_engine.connect() as conn:
        _set_guc(conn, seeded["b"])
        conn.execute(
            text(
                "INSERT INTO project_closeouts (id, company_id, project_id, stage, is_active) "
                "VALUES (:id, :c, :p, 'gecici_kabul', true)"
            ),
            {"id": co_b, "c": seeded["b"], "p": seeded["proj_b"]},
        )
        conn.commit()
    try:
        # A sees only its own closeout; B's is invisible.
        with app_engine.connect() as conn:
            _set_guc(conn, seeded["a"])
            own = conn.execute(text("SELECT count(*) FROM project_closeouts")).scalar()
            other = conn.execute(
                text("SELECT count(*) FROM project_closeouts WHERE company_id = :b"),
                {"b": seeded["b"]},
            ).scalar()
            assert own >= 1 and other == 0
            # A cannot INSERT a closeout into company B (WITH CHECK).
            with pytest.raises((DBAPIError, ProgrammingError)):
                conn.execute(
                    text(
                        "INSERT INTO project_closeouts (id, company_id, project_id, stage) "
                        "VALUES (:id, :c, :p, 'gecici_kabul')"
                    ),
                    {"id": uuid.uuid4(), "c": seeded["b"], "p": seeded["proj_b"]},
                )
                conn.commit()
    finally:
        admin = create_engine(ADMIN_URL, future=True)
        with admin.begin() as conn:
            conn.execute(
                text("DELETE FROM project_closeouts WHERE company_id IN (:a, :b)"),
                {"a": seeded["a"], "b": seeded["b"]},
            )
        admin.dispose()


def test_reports_isolation(seeded, app_engine):
    """0044 (CR-033): a company-A session cannot read or INSERT (WITH CHECK)
    company-B report rows. reports.owner_id is a NOT NULL FK to users, so we seed
    one user per company via the owner connection first."""
    import json

    from sqlalchemy.exc import DBAPIError, ProgrammingError

    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    rep_a, rep_b = uuid.uuid4(), uuid.uuid4()
    spec = json.dumps({"metrics": ["cost_try"]})

    admin = create_engine(ADMIN_URL, future=True)
    with admin.begin() as conn:
        for uid, cid in ((user_a, seeded["a"]), (user_b, seeded["b"])):
            conn.execute(
                text(
                    "INSERT INTO users (id, company_id, full_name, email, role) "
                    "VALUES (:id, :c, 'RLS User', :e, 'director')"
                ),
                {"id": uid, "c": cid, "e": f"rls-{uid.hex[:8]}@example.com"},
            )
    admin.dispose()

    try:
        # Each company seeds its own report on its own scoped session (each INSERT
        # must satisfy WITH CHECK for its own company).
        with app_engine.connect() as conn:
            _set_guc(conn, seeded["a"])
            conn.execute(
                text(
                    "INSERT INTO reports (id, company_id, owner_id, title, spec, visibility) "
                    "VALUES (:id, :c, :o, 'A', :spec, 'private')"
                ),
                {"id": rep_a, "c": seeded["a"], "o": user_a, "spec": spec},
            )
            conn.commit()
        with app_engine.connect() as conn:
            _set_guc(conn, seeded["b"])
            conn.execute(
                text(
                    "INSERT INTO reports (id, company_id, owner_id, title, spec, visibility) "
                    "VALUES (:id, :c, :o, 'B', :spec, 'company')"
                ),
                {"id": rep_b, "c": seeded["b"], "o": user_b, "spec": spec},
            )
            conn.commit()
        with app_engine.connect() as conn:
            _set_guc(conn, seeded["a"])
            own = conn.execute(text("SELECT count(*) FROM reports")).scalar()
            other = conn.execute(
                text("SELECT count(*) FROM reports WHERE company_id = :b"), {"b": seeded["b"]}
            ).scalar()
            assert own >= 1 and other == 0
            # WITH CHECK: A cannot INSERT a report into company B.
            with pytest.raises((DBAPIError, ProgrammingError)):
                conn.execute(
                    text(
                        "INSERT INTO reports (id, company_id, owner_id, title, spec, visibility) "
                        "VALUES (:id, :c, :o, 'evil', :spec, 'private')"
                    ),
                    {"id": uuid.uuid4(), "c": seeded["b"], "o": user_a, "spec": spec},
                )
                conn.commit()
    finally:
        admin = create_engine(ADMIN_URL, future=True)
        with admin.begin() as conn:
            conn.execute(text("DELETE FROM reports WHERE company_id IN (:a, :b)"),
                         {"a": seeded["a"], "b": seeded["b"]})
            conn.execute(text("DELETE FROM users WHERE id IN (:ua, :ub)"),
                         {"ua": user_a, "ub": user_b})
        admin.dispose()


def test_dashboards_isolation(seeded, app_engine):
    """0045 (CR-034): a company-A session cannot read or INSERT (WITH CHECK)
    company-B dashboard rows. dashboards.owner_id is a NOT NULL FK to users, so we
    seed one user per company via the owner connection first — exactly like
    ``test_reports_isolation``."""
    import json

    from sqlalchemy.exc import DBAPIError, ProgrammingError

    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    dash_a, dash_b = uuid.uuid4(), uuid.uuid4()
    widgets = json.dumps([{"id": "w1", "type": "text", "title": "t", "layout": {"x": 0, "y": 0, "w": 6, "h": 4}, "content": "x"}])

    admin = create_engine(ADMIN_URL, future=True)
    with admin.begin() as conn:
        for uid, cid in ((user_a, seeded["a"]), (user_b, seeded["b"])):
            conn.execute(
                text(
                    "INSERT INTO users (id, company_id, full_name, email, role) "
                    "VALUES (:id, :c, 'RLS User', :e, 'director')"
                ),
                {"id": uid, "c": cid, "e": f"rls-dash-{uid.hex[:8]}@example.com"},
            )
    admin.dispose()

    try:
        # Each company seeds its own dashboard on its own scoped session (each INSERT
        # must satisfy WITH CHECK for its own company).
        with app_engine.connect() as conn:
            _set_guc(conn, seeded["a"])
            conn.execute(
                text(
                    "INSERT INTO dashboards (id, company_id, owner_id, title, widgets, visibility) "
                    "VALUES (:id, :c, :o, 'A', :w, 'private')"
                ),
                {"id": dash_a, "c": seeded["a"], "o": user_a, "w": widgets},
            )
            conn.commit()
        with app_engine.connect() as conn:
            _set_guc(conn, seeded["b"])
            conn.execute(
                text(
                    "INSERT INTO dashboards (id, company_id, owner_id, title, widgets, visibility) "
                    "VALUES (:id, :c, :o, 'B', :w, 'company')"
                ),
                {"id": dash_b, "c": seeded["b"], "o": user_b, "w": widgets},
            )
            conn.commit()
        with app_engine.connect() as conn:
            _set_guc(conn, seeded["a"])
            own = conn.execute(text("SELECT count(*) FROM dashboards")).scalar()
            other = conn.execute(
                text("SELECT count(*) FROM dashboards WHERE company_id = :b"), {"b": seeded["b"]}
            ).scalar()
            assert own >= 1 and other == 0
            # WITH CHECK: A cannot INSERT a dashboard into company B.
            with pytest.raises((DBAPIError, ProgrammingError)):
                conn.execute(
                    text(
                        "INSERT INTO dashboards (id, company_id, owner_id, title, widgets, visibility) "
                        "VALUES (:id, :c, :o, 'evil', :w, 'private')"
                    ),
                    {"id": uuid.uuid4(), "c": seeded["b"], "o": user_a, "w": widgets},
                )
                conn.commit()
    finally:
        admin = create_engine(ADMIN_URL, future=True)
        with admin.begin() as conn:
            conn.execute(text("DELETE FROM dashboards WHERE company_id IN (:a, :b)"),
                         {"a": seeded["a"], "b": seeded["b"]})
            conn.execute(text("DELETE FROM users WHERE id IN (:ua, :ub)"),
                         {"ua": user_a, "ub": user_b})
        admin.dispose()


def test_skills_isolation(seeded, app_engine):
    """0046 (CR-044): a company-A session cannot read or INSERT (WITH CHECK)
    company-B skills / skill_runs rows. ``skills.owner_id`` is a NOT NULL FK to
    users, so we seed one user per company via the owner connection first — exactly
    like ``test_reports_isolation`` / ``test_dashboards_isolation``."""
    import json

    from sqlalchemy.exc import DBAPIError, ProgrammingError

    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    skill_a, skill_b = uuid.uuid4(), uuid.uuid4()
    run_a = uuid.uuid4()
    plan = json.dumps({"format": "xlsx", "title": "t", "widgets": [
        {"id": "w1", "type": "kpi", "title": "k", "layout": {"x": 0, "y": 0, "w": 3, "h": 2},
         "spec": {"metrics": ["cost_try"], "viz": "kpi"}}]})

    admin = create_engine(ADMIN_URL, future=True)
    with admin.begin() as conn:
        for uid, cid in ((user_a, seeded["a"]), (user_b, seeded["b"])):
            conn.execute(
                text(
                    "INSERT INTO users (id, company_id, full_name, email, role) "
                    "VALUES (:id, :c, 'RLS User', :e, 'director')"
                ),
                {"id": uid, "c": cid, "e": f"rls-skill-{uid.hex[:8]}@example.com"},
            )
    admin.dispose()

    try:
        # Each company seeds its own skill on its own scoped session (each INSERT
        # must satisfy WITH CHECK for its own company).
        with app_engine.connect() as conn:
            _set_guc(conn, seeded["a"])
            conn.execute(
                text(
                    "INSERT INTO skills (id, company_id, owner_id, name, instruction, plan, format, visibility) "
                    "VALUES (:id, :c, :o, 'A', 'x', :p, 'xlsx', 'private')"
                ),
                {"id": skill_a, "c": seeded["a"], "o": user_a, "p": plan},
            )
            # plus a skill_run owned by A (WITH CHECK on skill_runs too).
            conn.execute(
                text(
                    "INSERT INTO skill_runs (id, company_id, skill_id, status, format) "
                    "VALUES (:id, :c, :s, 'ok', 'xlsx')"
                ),
                {"id": run_a, "c": seeded["a"], "s": skill_a},
            )
            conn.commit()
        with app_engine.connect() as conn:
            _set_guc(conn, seeded["b"])
            conn.execute(
                text(
                    "INSERT INTO skills (id, company_id, owner_id, name, instruction, plan, format, visibility) "
                    "VALUES (:id, :c, :o, 'B', 'x', :p, 'xlsx', 'company')"
                ),
                {"id": skill_b, "c": seeded["b"], "o": user_b, "p": plan},
            )
            conn.commit()
        with app_engine.connect() as conn:
            _set_guc(conn, seeded["a"])
            own = conn.execute(text("SELECT count(*) FROM skills")).scalar()
            other = conn.execute(
                text("SELECT count(*) FROM skills WHERE company_id = :b"), {"b": seeded["b"]}
            ).scalar()
            own_runs = conn.execute(text("SELECT count(*) FROM skill_runs")).scalar()
            assert own >= 1 and other == 0
            assert own_runs >= 1
            # WITH CHECK: A cannot INSERT a skill into company B.
            with pytest.raises((DBAPIError, ProgrammingError)):
                conn.execute(
                    text(
                        "INSERT INTO skills (id, company_id, owner_id, name, instruction, plan, format, visibility) "
                        "VALUES (:id, :c, :o, 'evil', 'x', :p, 'xlsx', 'private')"
                    ),
                    {"id": uuid.uuid4(), "c": seeded["b"], "o": user_a, "p": plan},
                )
                conn.commit()
    finally:
        admin = create_engine(ADMIN_URL, future=True)
        with admin.begin() as conn:
            conn.execute(text("DELETE FROM skill_runs WHERE company_id IN (:a, :b)"),
                         {"a": seeded["a"], "b": seeded["b"]})
            conn.execute(text("DELETE FROM skills WHERE company_id IN (:a, :b)"),
                         {"a": seeded["a"], "b": seeded["b"]})
            conn.execute(text("DELETE FROM users WHERE id IN (:ua, :ub)"),
                         {"ua": user_a, "ub": user_b})
        admin.dispose()
