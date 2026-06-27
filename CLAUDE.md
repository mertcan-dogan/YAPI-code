# YAPI — Project Guide for Claude Code

Construction-finance SaaS for Turkish contractors. UI language **Turkish (tr-TR)**, currency **TRY**.
**`main` IS production:** pushing to `origin/main` AUTO-DEPLOYS (Railway = backend, Vercel = frontend). Treat it as live.

## Architecture
- **`backend/`** — Python FastAPI + SQLAlchemy 2.0 + Alembic; PostgreSQL (Supabase, Row-Level Security).
  - `app/api/` — HTTP endpoints, one file per domain (costs, invoices, vendors, equipment, automations, ai, …). 32 routers.
  - `app/services/` — business logic / the real work (financials, approvals, automations, fx, vendor_backfill, assurance, …). 27 files.
  - `app/calculations/` — **pure financial math** (money, project_financials, equipment, subcontractor). HIGH blast-radius — change only with the guard tests green.
  - `app/models/` — SQLAlchemy tables (30). `app/schemas/` — Pydantic request/response (15). `app/middleware/`, `app/utils/`.
  - `migrations/versions/` — Alembic DB migrations. **Current head: `0045_dashboards`. Next id: 0046.**
  - `tests/` — pytest, 114 files.
- **`frontend/`** — React 18 + Vite + TypeScript + Tailwind + Zustand + Recharts + React Hook Form/Zod.
  - `src/pages/` — one per route (30). `src/components/` — ui/charts/layout (71). `src/lib/` — API client + `requestCache`. `src/store/`, `src/utils/`, `src/hooks/`.
- Root `*.md` — change-request specs (`CR-0xx-*.md`), roadmap, assessments. Planning docs; most are local-only (not committed).

## Golden rules — do not break
1. **Never push to `origin/main` without explicit human approval.** It deploys to live prod. Work on a branch; the human decides when to merge.
2. **Branch from the latest `origin/main`.** One task per branch. Names: `feat/...`, `fix/...`, `cr-0xx-...`.
3. **Only ONE migration in flight at a time.** If your task needs a DB schema change, the new migration is numbered after the current head (today 0045) and must be the ONLY new one. If you're told another agent owns migrations for now, do **not** add one.
4. **Test before declaring done / merge-ready** — all must be green:
   - Backend: `cd backend && python -m pytest -q` (use the repo venv).
   - Frontend: `cd frontend && npm test` **and** `npm run build`.
   - These guard suites protect financial integrity and must stay green: CR-011 agent-never-writes-directly (`test_cr011c_*`, `test_cr011e_*`), CR-023 committed cost (`test_cr023_*`, `test_cr0231_*`), CR-031 P&L no-double-count (`test_cr031*`).
5. **No migration ⇒ confirm `alembic heads` is unchanged (0045).** A new migration ⇒ it must be the single new head; validate it applies + downgrades on a local Postgres before merge (never test against prod).
6. **After any deploy, verify prod:** `GET https://yapi-code-production.up.railway.app/health?cb=<timestamp>` and check `db_revision` == expected (the URL caches — always add `?cb=`).
7. **Keep changes scoped** to the task's files; don't refactor unrelated code. The money/cost engine is sacred — preserve the tested invariants: no double-count, the AI agent only *proposes* (writes go through human approval), cost data stays authoritative.
8. UI strings are Turkish (tr-TR); amounts are TRY (USD/GBP are display-only conversions).

## Run / test commands
- Backend: deps `cd backend && pip install -r requirements.txt` (or `./venv`); tests `python -m pytest -q`; migrate (local only) `alembic upgrade head`.
- Frontend: `cd frontend && npm install`; dev `npm run dev`; tests `npm test`; build `npm run build`.

## Parallel agents
Each agent: its own git worktree, its own branch off the latest `origin/main`, on NON-overlapping files. Only ONE agent ever touches `backend/migrations/`. Merge one branch at a time → re-test → verify `/health` → then start the next. Add `.claude/worktrees/` to `.gitignore`.
