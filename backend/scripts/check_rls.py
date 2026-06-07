"""RLS diagnostic — verify policies and FORCE status on every table.

Run from backend/ with .env populated (DATABASE_URL → your Supabase Postgres):

    python scripts/check_rls.py

It prints, per table: whether RLS is enabled, whether it is FORCED (which is what
broke the API), the policies that exist, and a row count visible to the backend's
connection. After applying migration 0005, FORCE should be False everywhere and
the counts should be non-zero where data exists.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

from sqlalchemy import text

from app.db import get_engine

TABLES = [
    "companies", "users", "projects", "cost_entries", "client_invoices",
    "subcontractors", "equipment_log", "budget_line_items", "audit_log",
    "ai_alerts", "custom_cost_categories",
]


def main() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        print("\n=== RLS STATUS (relrowsecurity / relforcerowsecurity) ===")
        rows = conn.execute(text(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = ANY(:tables)
            ORDER BY c.relname
            """
        ), {"tables": TABLES}).fetchall()
        forced_any = False
        for name, enabled, forced in rows:
            flag = "  <-- FORCED (blocks the backend!)" if forced else ""
            if forced:
                forced_any = True
            print(f"  {name:<24} enabled={enabled!s:<5} forced={forced!s:<5}{flag}")

        print("\n=== POLICIES (pg_policies) ===")
        pols = conn.execute(text(
            """
            SELECT tablename, policyname, cmd
            FROM pg_policies WHERE schemaname = 'public'
            ORDER BY tablename, policyname
            """
        )).fetchall()
        by_table: dict[str, list[str]] = {}
        for t, p, cmd in pols:
            by_table.setdefault(t, []).append(f"{p} ({cmd})")
        for t in TABLES:
            ps = by_table.get(t, [])
            mark = "" if ps else "  <-- NO POLICIES"
            print(f"  {t}:{mark}")
            for p in ps:
                print(f"      - {p}")

        print("\n=== ROW COUNTS visible to this connection ===")
        for t in TABLES:
            try:
                n = conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
                print(f"  {t:<24} {n}")
            except Exception as exc:  # noqa: BLE001
                print(f"  {t:<24} ERROR: {exc}")

        # Secondary cause: projects belonging to a company with no matching user.
        print("\n=== COMPANY ID CROSS-CHECK (projects vs users) ===")
        proj = conn.execute(text(
            "SELECT company_id, count(*) FROM projects WHERE is_deleted = false GROUP BY company_id"
        )).fetchall()
        users = conn.execute(text(
            "SELECT company_id, count(*) FROM users WHERE is_deleted = false GROUP BY company_id"
        )).fetchall()
        user_companies = {str(c) for c, _ in users}
        print("  Users by company:")
        for c, n in users:
            print(f"      company={c}  users={n}")
        print("  Projects by company:")
        for c, n in proj:
            mark = "" if str(c) in user_companies else "  <-- NO USER IN THIS COMPANY (API will look empty for everyone)"
            print(f"      company={c}  projects={n}{mark}")

    print("\n[RESULT]", "FORCE still set on some tables — run `alembic upgrade head` (migration 0005)."
          if forced_any else "No tables are FORCED. Backend service role can read; RLS still protects direct access.")


if __name__ == "__main__":
    main()
