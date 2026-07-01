# CR-012 — Otomasyonlar: Scheduler (Cron) Setup

The recurring-digest automation is **time-driven**. There is no in-process timer
in the app (a Railway web dyno restarts/scales → a wall-clock timer would miss or
double-fire). Instead an **external cron** hits one authenticated internal
endpoint on a schedule:

```
POST  https://<your-app>/api/v1/internal/automations/run-due
Header:  X-Internal-Secret: <INTERNAL_CRON_SECRET>
```

The endpoint is **idempotent** (driven by each automation's `next_run_at` + a
per-period guard), so calling it **hourly** is safe — a digest fires **at most
once per period** even if the cron ticks late or twice. Document auto-file is
event-driven (runs on upload) and needs **no** cron.

Production base URL: `https://yapi-code-production.up.railway.app`
→ full endpoint: `https://yapi-code-production.up.railway.app/api/v1/internal/automations/run-due`

---

## 1. Create the secret (one time)

Generate a long random secret (do **NOT** commit it anywhere):

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

In **Railway → your API service → Variables**, add:

| Variable | Value | Notes |
|---|---|---|
| `INTERNAL_CRON_SECRET` | *(the generated secret)* | Gates the endpoint. Blank ⇒ endpoint rejects everything (401). |
| `EMAIL_VERIFIED_DOMAIN` | `0` (set to `1` later) | Keep `0` until a verified Resend domain is configured. While `0`, digests deliver **in-app only**; email stays off. |

Redeploy the API service so the new variables load.

---

## 2. Option A — Railway native Cron (recommended)

Railway runs a service's start command on a cron schedule. Add a **second
service** in the same project pointing at the same repo (or a tiny image) with:

- **Cron Schedule:** `0 * * * *`  (top of every hour)
- **Start Command:**

```bash
curl -fsS -X POST \
  "https://yapi-code-production.up.railway.app/api/v1/internal/automations/run-due" \
  -H "X-Internal-Secret: $INTERNAL_CRON_SECRET"
```

Add the same `INTERNAL_CRON_SECRET` variable to this cron service (or share it at
the project level). Railway starts the container on schedule, runs the curl, and
exits — exactly what a cron job should do.

> Tip: `-f` makes curl exit non-zero on an HTTP error so a failed tick shows up
> in the Railway cron run logs.

---

## 3. Option B — cron-job.org (fallback, no Railway cron needed)

1. Sign in at https://cron-job.org and **Create cronjob**.
2. **URL:** `https://yapi-code-production.up.railway.app/api/v1/internal/automations/run-due`
3. **Schedule:** every hour (`0 * * * *`).
4. **Request method:** `POST`.
5. **Advanced → Headers:** add
   `X-Internal-Secret: <the same secret>`.
6. Save and enable. Check the execution history after the first hour.

---

## 4. Verify it works

Locally (or against prod with the real secret):

```bash
# Wrong/missing secret -> 401
curl -i -X POST "$APP_URL/api/v1/internal/automations/run-due"

# Correct secret -> 200 with counts
curl -s -X POST "$APP_URL/api/v1/internal/automations/run-due" \
  -H "X-Internal-Secret: $INTERNAL_CRON_SECRET"
# => {"success":true,"data":{"due":N,"ran":N,"skipped":N,"errored":0}}
```

`ran` counts digests sent this tick; `skipped` counts due automations that already
ran this period (the idempotency guard); `errored` counts automations that failed
(captured per-row in `automation_runs`, never aborting the others).

---

## 5. Security notes

- The endpoint has **no user auth** — it is gated **only** by the secret header,
  using a constant-time compare. A blank `INTERNAL_CRON_SECRET` keeps it closed.
- **Never commit the secret.** It lives only in Railway/cron-job.org env config.
- Each run is **company-scoped**: a tick for company A only reads/writes company
  A's data.
- Email is **best-effort** and can never fail a run; until `EMAIL_VERIFIED_DOMAIN=1`
  digests are in-app only.
