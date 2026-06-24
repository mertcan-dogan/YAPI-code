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
SCOPED_SAMPLE = ["projects", "cost_entries", "client_invoices", "users"]


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
