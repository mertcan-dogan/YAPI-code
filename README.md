# Yapı — İnşaat Proje Yönetim Yazılımı

**Construction Project Management SaaS** for Turkish civil & infrastructure contractors.
A real-time financial control centre that bridges site-level execution and company-level
financial oversight — the gap between Excel and accounting software.

> Built to the Yapı PRD v1.0. Primary language **Turkish (tr-TR)**, primary currency **TRY**.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite + TypeScript, Tailwind CSS, Recharts, Zustand, React Hook Form + Zod |
| Backend | Python FastAPI, SQLAlchemy 2.0 + Alembic |
| Database | PostgreSQL (Supabase) with Row-Level Security |
| Auth | Supabase Auth (JWT) |
| AI | Anthropic Claude API (`claude-sonnet-4-5`) |
| Email | Resend · **PDF** WeasyPrint · **Excel** openpyxl |
| Hosting | Vercel (frontend) · Railway/Render (backend) |

---

## Repository Structure

```
yapi/
├── frontend/          # React + Vite app
│   └── src/
│       ├── components/ (ui, charts, layout)
│       ├── pages/      (one per route)
│       ├── hooks/  store/  api/  lib/  utils/  constants/  types/
├── backend/
│   └── app/
│       ├── api/         # FastAPI routers per domain
│       ├── models/      # SQLAlchemy ORM
│       ├── schemas/     # Pydantic request/response
│       ├── services/    # Business logic
│       ├── calculations/# Financial calculation engine (Section 7)
│       ├── middleware/  # Auth, rate limit, error handling
│       └── main.py
│   ├── migrations/      # Alembic
│   └── tests/           # Pytest
└── docker-compose.yml
```

---

## Prerequisites

- **Node.js** ≥ 20 and **npm** ≥ 10
- **Python** ≥ 3.12
- A **Supabase** project (Postgres + Auth + Storage), region `eu-central-1` (Frankfurt)
- API keys: **Anthropic** (AI), **Resend** (email) — optional for local dev (features degrade gracefully)

---

## Quick Start (Docker)

```bash
# from the repository root — brings up postgres + backend + frontend
export SUPABASE_URL=...        # set the keys you have
export SUPABASE_ANON_KEY=...
export SUPABASE_SERVICE_KEY=...
export JWT_SECRET=...          # Supabase project JWT secret
docker compose up --build
```

- Frontend → http://localhost:5173
- Backend  → http://localhost:8000 (docs at `/docs`)

---

## Local Development (without Docker)

### 1. Backend

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate    # Windows
# source .venv/bin/activate                          # macOS/Linux
pip install -r requirements.txt

cp .env.example .env          # fill in the values
alembic upgrade head          # create schema + enable RLS

uvicorn app.main:app --reload --port 8000
```

Health check: `GET http://localhost:8000/health` → `{"status":"ok"}`

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env          # set VITE_API_BASE_URL + Supabase anon key
npm run dev
```

---

## Environment Variables

### Backend (`backend/.env`)
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Postgres connection string (`postgresql+psycopg://...`) |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | Supabase project + **service** key (backend only) |
| `JWT_SECRET` | Supabase JWT signing secret (verifies tokens) |
| `ANTHROPIC_API_KEY` | Claude API key (AI features) |
| `RESEND_API_KEY` | Transactional email |
| `FRONTEND_URL` | CORS allowed origin |
| `ENVIRONMENT` | `development` / `staging` / `production` |

### Frontend (`frontend/.env`)
| Variable | Description |
|----------|-------------|
| `VITE_API_BASE_URL` | Backend base URL, e.g. `http://localhost:8000/api/v1` |
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | **Public anon** key only — never the service key |

> 🔒 `SUPABASE_SERVICE_KEY` and `ANTHROPIC_API_KEY` are backend-only and must
> never appear in the frontend bundle.

---

## Database & Row-Level Security

Migrations live in `backend/migrations/`:

- `0001_initial_schema` — all tables from PRD Section 2.3 (requires `pgcrypto`)
- `0002_enable_rls` — RLS policies isolating every tenant by `company_id`
  (Section 2.4), plus append-only protection on `audit_log`.

```bash
alembic upgrade head     # apply
alembic downgrade -1     # roll back the last migration
```

After migrating, enable **Point-in-Time Recovery** in the Supabase dashboard and
configure the Auth email templates in Turkish.

---

## Testing

```bash
cd backend
pytest -q                       # full suite
pytest tests/test_calculations.py   # financial engine only
```

- `test_calculations.py` — every formula in Section 7 + RAG boundary cases (5% / 10%).
- `test_api.py` — auth (401), cross-company isolation (404), soft delete, invoice
  uniqueness, Turkish validation (422), audit logging, computed columns.
  Runs on in-memory SQLite via portable column types — **no Postgres required**.

Frontend type-check / build:
```bash
cd frontend && npm run build
```

---

## Deployment

### Frontend — Vercel
- Build command `npm run build`, output `dist`, framework **Vite**.
- `vercel.json` includes SPA rewrite rules. Set the `VITE_*` env vars in the Vercel dashboard.

### Backend — Railway / Render
- A `Dockerfile` is provided (`backend/Dockerfile`) with WeasyPrint system libs.
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check: `GET /health`. Set all backend env vars in the dashboard.

### Database — Supabase
- Create the project in `eu-central-1`, run `alembic upgrade head`, enable RLS & PITR.

---

## Troubleshooting — 401 on `/auth/me`

The backend verifies Supabase access tokens in two modes, auto-selected by the
token header: legacy **HS256** (shared `JWT_SECRET`) and new **ES256/RS256**
(asymmetric signing keys, verified via JWKS). With `DEBUG_AUTH=1` (default
outside production) the backend logs the algorithm, kid, JWKS URL and the exact
failure for every rejected token, and the browser console logs whether a token
was attached.

Run the standalone diagnostic with a real token (copied from the browser):

```bash
cd backend
python scripts/debug_auth.py "<access_token>"
```

It prints the token header/claims, the kids published by your JWKS endpoint, and
the precise verification result. Common causes:

| Symptom in logs | Cause | Fix |
|---|---|---|
| `no/invalid Authorization header` | Frontend isn't sending the token | Check `VITE_SUPABASE_*` env and that the session exists |
| `token kid NOT present in JWKS` | Key rotation / wrong project | Confirm `SUPABASE_JWKS_URL` matches the project that issued the token |
| `cryptography package missing` | ES/RS can't be verified | `pip install -r requirements.txt` (`pyjwt[crypto]`) |
| `token valid … but no active users row` | Auth user has no `public.users` row | Create the company + `users` row for that `sub` (invite/onboarding) |

## Key Features

- **Company & Project dashboards** — KPI cards, RAG health, S-curve, cash-flow charts.
- **Budget vs Actual** — per-category cost control with editable PM forecasts.
- **Hakediş (progress billing)** — client invoices, retention, collection tracking.
- **Subcontractors, Equipment, Cash Flow** — full tracking per project.
- **Payment reminders** — cross-project payables/receivables with colour-coded urgency.
- **AI** — daily briefing, 5-type alert engine, PDF invoice field extraction (graceful degradation).
- **Reports** — Turkish PDF export. **Excel import** for historical cost data.
- **Security** — Supabase JWT, RLS, audit trail, server-side validation, rate limiting.

---

*Yapı — Construction Project Management SaaS — v1.0*
