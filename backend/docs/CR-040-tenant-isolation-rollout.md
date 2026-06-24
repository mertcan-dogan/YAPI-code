# CR-040 — Real DB-level tenant isolation: rollout & rollback

This change makes Postgres Row-Level Security actually enforce company isolation,
instead of relying only on application-code `company_id` filters.

**It is inert until you flip two env vars.** Merging/deploying the code with
`ADMIN_DATABASE_URL` unset changes nothing: every path falls back to the current
`DATABASE_URL` (service_role, which has BYPASSRLS), so behaviour is identical to
today. Isolation activates only when you complete the steps below.

---

## How it works (one paragraph)

- The app keeps connecting directly to Postgres. RLS only bites a role **without**
  `BYPASSRLS`, so we add a dedicated **`yapi_app`** login role (`NOBYPASSRLS`) and
  point `DATABASE_URL` at it.
- Each request sets a transaction-local GUC `app.current_company` to the caller's
  company id; migration 0040's policies filter every company-scoped table on it.
- Paths that must NOT be tenant-scoped (Alembic migrations, the auth user lookup,
  the cron scheduler, the login-stamp write) use a separate **escalated** session
  built from `ADMIN_DATABASE_URL` (the service_role/owner URL).

---

## Step 1 — Create the `yapi_app` role (run ONCE, in Supabase)

Run this in the **Supabase SQL editor** (or via the Supabase MCP `execute_sql`)
against the project. It is ops, not an Alembic migration (it needs a secret
password and is a one-time cluster act).

```sql
-- 1) The role RLS will actually apply to. Pick a strong password and KEEP IT
--    (you'll paste it into Railway in Step 2). NOBYPASSRLS is the whole point.
CREATE ROLE yapi_app LOGIN PASSWORD 'REPLACE_WITH_A_STRONG_SECRET'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

-- 2) Let it use the schema and read/write the data (RLS still constrains WHICH
--    rows — these grants are table-level privileges, orthogonal to row policies).
GRANT USAGE ON SCHEMA public TO yapi_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO yapi_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO yapi_app;

-- 3) CRITICAL: future tables created by migrations (run as the owner) must also
--    be reachable by yapi_app, else the next migration's new table 500s for the
--    app. ALTER DEFAULT PRIVILEGES auto-grants going forward.
--    Run this AS THE ROLE THAT OWNS/CREATES TABLES (the migration role — usually
--    `postgres`). If you run the block as postgres, this line is correct as-is.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO yapi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO yapi_app;
```

Notes:
- The policies compare `company_id` to a **session GUC literal**, not a subquery
  into `users`, so `yapi_app` needs no special access to `users` for isolation to
  work (and there's no recursive-policy hazard).
- `yapi_app` must NOT be granted `BYPASSRLS` and must NOT be a member of a
  superuser/`postgres` role — verify with:
  `SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname='yapi_app';`
  Both must be `f`.

Build the connection string for `yapi_app` the same shape as your current
`DATABASE_URL`, just swapping user/password (keep the same host/port/db and any
pooler settings):

```
postgresql+psycopg://yapi_app:REPLACE_WITH_A_STRONG_SECRET@<HOST>:<PORT>/<DB>?<same-params>
```

## Step 2 — Set the Railway env vars (backend service)

In the Railway backend service → **Variables**:

1. **Add** `ADMIN_DATABASE_URL` = your *current* `DATABASE_URL` value (the
   service_role/owner connection). This is what migrations + escalated paths use.
2. **Change** `DATABASE_URL` to the new **`yapi_app`** connection string from Step 1.

Deploy. On boot, migrations run via `ADMIN_DATABASE_URL` (owner) and the app
serves requests via `yapi_app` (RLS-enforced).

> Order matters only in that `ADMIN_DATABASE_URL` must be set **before** (or in the
> same deploy as) the `DATABASE_URL` switch — otherwise migrations would try to run
> as `yapi_app` and fail. Setting both in one deploy is fine.

## Step 3 — Verify after deploy

- `GET https://yapi-code-production.up.railway.app/health?cb=<timestamp>` →
  `db_revision` should be `0040_rls_guc_isolation`, `db_migration_ok: true`.
  (Health only reads `alembic_version`; it does **not** prove isolation — see the
  A/B matrix in `tests/test_rls_isolation_pg.py`.)
- Log in as a real user and confirm dashboards/lists show **that company's** data
  (not empty). Empty-for-your-own-company ⇒ the GUC isn't being set → roll back.

---

## Rollback (fastest first)

1. **Instant, env-only:** set `DATABASE_URL` back to the service_role value (same
   as `ADMIN_DATABASE_URL`) and redeploy. service_role has BYPASSRLS, so RLS stops
   applying immediately and every read works as before. No DB change.
2. **Revert policies too (optional):** `alembic downgrade -1` (0040 → 0039)
   restores the previous `auth.uid()`-based policies. Combine with (1).

**Reading the symptom:**
- *Everyone* sees empty data → GUC wiring problem → roll back via (1).
- Users see *their own* data but never other companies' → isolation is working as
  intended; do nothing.

---

## Validating the A/B matrix on real Postgres (before merge)

SQLite can't exercise RLS. Run the proof against a throwaway Supabase **branch**
(or any real Postgres) with 0040 applied + `yapi_app` created:

```
RLS_ADMIN_URL=postgresql+psycopg://postgres:...@host/db \
RLS_APP_URL=postgresql+psycopg://yapi_app:...@host/db \
python -m pytest -q tests/test_rls_isolation_pg.py
```

It asserts: A can't read/insert/update/delete B's rows, B mirrors, and an unset
GUC is fail-closed (zero rows). The test is skipped when those env vars are unset,
so it never affects the normal SQLite suite.
```
