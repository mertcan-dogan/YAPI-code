"""CR-012 — Otomasyonlar service: scheduling + the recurring-digest template.

This module owns the time-driven side of Automations:

* **Scheduling math** — ``compute_next_run`` turns a ``recurring_digest`` config
  (cadence / day / hour / tz) into the next UTC fire time, and ``_same_period``
  is the idempotency guard so a duplicate or late cron tick sends **at most once
  per period** (§6).
* **The scheduler** — ``run_due_automations`` finds every enabled scheduled
  automation whose ``next_run_at <= now`` *across all companies*, runs each one
  company-scoped, writes an ``automation_runs`` audit row, and advances
  ``last_run_at`` / ``next_run_at``. A failure in one automation never aborts the
  others. Driven by the external cron → ``POST /internal/automations/run-due``.
* **Template B (recurring digest)** — composes a per-project gelir/maliyet/net +
  marj + bekleyen-tahsilat summary from the authoritative read-only financials,
  delivers it as an in-app ``Notification`` to directors + project managers, and
  (best-effort, gated on a verified domain) an email. Email **must never fail the
  run** (§3.2).

The document-auto-file template is event-driven (on upload) and lives in
``api/document_capture.py`` + ``services/approvals.py``; it needs no scheduler.
"""
import calendar
import logging
import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.automation import (
    TEMPLATE_RECURRING_DIGEST,
    Automation,
    AutomationRun,
)
from app.models.company import Company
from app.models.project import Project
from app.models.user import User
from app.constants import ROLE_DIRECTOR

logger = logging.getLogger("yapi.automations")

DEFAULT_TZ = "Europe/Istanbul"
DEFAULT_HOUR = 8


# --------------------------------------------------------------------------- #
# Timezone + scheduling math
# --------------------------------------------------------------------------- #
def _tz(name: str | None):
    """Resolve a tz name, falling back to a fixed Istanbul offset (UTC+3) when the
    zoneinfo database is unavailable (e.g. a stripped Windows host without tzdata).
    Istanbul has had a fixed +03:00 offset with no DST since 2016, so the fallback
    is correct for the only tz v1 ships."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:  # noqa: BLE001 — missing tzdata must not break scheduling
        return timezone(timedelta(hours=3))


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalise a possibly-naive datetime (SQLite returns naive) to aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_next_run(config: dict, after: datetime) -> datetime:
    """Next UTC fire time strictly after ``after`` for a recurring-digest config.

    Weekly: the next ``day_of_week`` (Mon=0) at ``hour`` local. Monthly: the next
    ``day_of_month`` at ``hour`` local (clamped to the month's last day). Always
    returns a tz-aware UTC datetime.
    """
    after = _as_utc(after) or datetime.now(timezone.utc)
    tz = _tz(config.get("tz"))
    local_after = after.astimezone(tz)
    hour = int(config.get("hour", DEFAULT_HOUR))
    cadence = config.get("cadence", "weekly")

    if cadence == "monthly":
        dom = int(config.get("day_of_month", 1))
        cand = _month_dt(local_after.year, local_after.month, dom, hour, tz)
        if cand <= local_after:
            y, m = (local_after.year + 1, 1) if local_after.month == 12 else (local_after.year, local_after.month + 1)
            cand = _month_dt(y, m, dom, hour, tz)
        return cand.astimezone(timezone.utc)

    # weekly (default)
    dow = int(config.get("day_of_week", 0))
    days_ahead = (dow - local_after.weekday()) % 7
    cand = datetime.combine(local_after.date() + timedelta(days=days_ahead), time(hour=hour), tzinfo=tz)
    if cand <= local_after:
        cand += timedelta(days=7)
    return cand.astimezone(timezone.utc)


def _month_dt(year: int, month: int, day: int, hour: int, tz) -> datetime:
    last_day = calendar.monthrange(year, month)[1]
    return datetime.combine(
        datetime(year, month, min(day, last_day)).date(), time(hour=hour), tzinfo=tz
    )


def _period_key(config: dict, dt: datetime) -> str:
    """A per-period identifier in the config's tz: ISO year-week (weekly) or
    year-month (monthly). Two timestamps in the same period share a key."""
    tz = _tz(config.get("tz"))
    local = (_as_utc(dt) or datetime.now(timezone.utc)).astimezone(tz)
    if config.get("cadence") == "monthly":
        return f"{local.year}-M{local.month:02d}"
    iso = local.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _same_period(config: dict, a: datetime | None, b: datetime) -> bool:
    """Idempotency guard: True when ``a`` already falls in ``b``'s period."""
    if a is None:
        return False
    return _period_key(config, a) == _period_key(config, b)


# --------------------------------------------------------------------------- #
# Template B — recurring digest
# --------------------------------------------------------------------------- #
def _scope_projects(db: Session, company: Company, config: dict) -> list[Project]:
    """Active projects for the company, optionally narrowed by config.scope.

    Company-scoped by construction (a cron run for company A never reads company
    B's projects). scope='all' → every active project; {project_ids:[...]} → just
    those, still filtered to the company.
    """
    projects = db.execute(
        select(Project).where(
            Project.company_id == company.id,
            Project.is_deleted.is_(False),
            Project.status == "active",
        )
    ).scalars().all()
    scope = config.get("scope", "all")
    if isinstance(scope, dict) and scope.get("project_ids"):
        wanted = {str(x) for x in scope["project_ids"]}
        projects = [p for p in projects if str(p.id) in wanted]
    return list(projects)


def build_digest(db: Session, company: Company, config: dict) -> dict:
    """Compose the digest content from the authoritative read-only financials.

    Returns rows (per project: marj / bekleyen / net) + a portfolio rollup. This
    never writes and never mutates cost/revenue — it only reads ``project_financials``.
    """
    from app.calculations.money import D
    from app.services.financials import project_financials
    from app.utils.format import format_currency_tr, format_pct_tr

    projects = _scope_projects(db, company, config)
    rows = []
    total_outstanding = D(0)
    total_contract = D(0)
    for p in projects:
        f = project_financials(db, p)
        total_outstanding += D(f["total_outstanding_try"])
        total_contract += D(f["contract_value_try"])
        rows.append({
            "name": p.name,
            "margin": format_pct_tr(f["margin_pct"]),
            "margin_value": float(f["margin_pct"]),
            "outstanding": format_currency_tr(f["total_outstanding_try"]),
            "rag": f["rag_status"],
            "overdue_days": f.get("max_overdue_days", 0),
        })
    return {
        "project_count": len(rows),
        "rows": rows,
        "total_outstanding": format_currency_tr(total_outstanding),
        "total_contract": format_currency_tr(total_contract),
    }


def _digest_recipients(db: Session, company: Company, projects: list[Project]) -> list[User]:
    """Directors (company-wide) + each scoped project's manager, de-duplicated."""
    by_id: dict[uuid.UUID, User] = {}
    directors = db.execute(
        select(User).where(
            User.company_id == company.id,
            User.role == ROLE_DIRECTOR,
            User.is_deleted.is_(False),
        )
    ).scalars().all()
    for u in directors:
        by_id[u.id] = u
    for p in projects:
        pm_id = getattr(p, "project_manager_id", None)
        if pm_id and pm_id not in by_id:
            pm = db.get(User, pm_id)
            if pm and not pm.is_deleted:
                by_id[pm.id] = pm
    return list(by_id.values())


def _digest_body(digest: dict) -> str:
    """Compact Türkçe in-app body listing each project's marj + bekleyen tahsilat."""
    if not digest["rows"]:
        return "Bu dönem için aktif proje bulunmuyor."
    lines = [f"{r['name']}: marj {r['margin']}, bekleyen {r['outstanding']}" for r in digest["rows"][:8]]
    lines.append(f"Toplam bekleyen tahsilat: {digest['total_outstanding']}")
    return "\n".join(lines)


def run_recurring_digest(db: Session, automation: Automation, company: Company,
                         now: datetime, config: dict) -> dict:
    """Compose + deliver one digest. In-app delivery is reliable; email is
    best-effort and gated on a verified domain — it can never fail the run."""
    from app.services.notifications import create_notification
    from app.utils.format import format_date_tr

    digest = build_digest(db, company, config)
    projects = _scope_projects(db, company, config)
    recipients = _digest_recipients(db, company, projects)
    delivery = (config.get("delivery") or {})
    body = _digest_body(digest)
    title = f"Periyodik Özet — {digest['project_count']} proje ({format_date_tr(now.date())})"

    notif_count = 0
    if delivery.get("in_app", True):
        for u in recipients:
            create_notification(
                db, company_id=company.id, title=title[:200], body=body,
                type="digest", severity="low", user_id=u.id,
            )
            notif_count += 1

    # Email — best-effort, never fails the run, only attempted on a verified domain.
    email_count = 0
    email_skipped_reason = None
    if delivery.get("email"):
        from app.config import settings

        if not settings.email_verified_domain:
            email_skipped_reason = "domain_unverified"
        else:
            try:
                from app.services.email_service import email_service

                to = [u.email for u in recipients if u.email]
                if to:
                    res = email_service.send_weekly_summary_email(company, digest["rows"], to)
                    if res.get("sent"):
                        email_count = len(to)
                    else:
                        email_skipped_reason = res.get("reason")
            except Exception as exc:  # noqa: BLE001 — email never breaks the run
                logger.error("Digest email failed (company=%s): %s", company.id, exc)
                email_skipped_reason = "error"

    summary = {
        "projects": digest["project_count"],
        "notifications": notif_count,
        "emails": email_count,
    }
    if email_skipped_reason:
        summary["email_skipped"] = email_skipped_reason
    return summary


# --------------------------------------------------------------------------- #
# Scheduler entry point (called by the internal endpoint)
# --------------------------------------------------------------------------- #
def _record_run(db: Session, automation: Automation, started: datetime,
                status: str, summary: dict | None, error: str | None = None) -> None:
    db.add(AutomationRun(
        automation_id=automation.id,
        company_id=automation.company_id,
        template_key=automation.template_key,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
        status=status,
        summary=summary,
        error=error,
    ))
    db.flush()


def run_due_automations(db: Session, now: datetime | None = None) -> dict:
    """Run every enabled scheduled automation whose ``next_run_at <= now`` across
    all companies. Idempotent (next_run_at + the per-period guard), so it's safe to
    call as often as hourly. Returns counts. Commits once at the end.
    """
    now = _as_utc(now) or datetime.now(timezone.utc)
    due = db.execute(
        select(Automation).where(
            Automation.enabled.is_(True),
            Automation.is_deleted.is_(False),
            Automation.template_key == TEMPLATE_RECURRING_DIGEST,
            Automation.next_run_at.is_not(None),
            Automation.next_run_at <= now,
        )
    ).scalars().all()

    ran = skipped = errored = 0
    for automation in due:
        config = automation.config or {}
        company = db.get(Company, automation.company_id)
        if company is None:
            continue
        # Idempotency: a duplicate/late tick within the same period sends nothing.
        if _same_period(config, automation.last_run_at, now):
            automation.next_run_at = compute_next_run(config, now)
            _record_run(db, automation, now, "skipped", {"reason": "already_ran_this_period"})
            skipped += 1
            continue
        try:
            summary = run_recurring_digest(db, automation, company, now, config)
            automation.last_run_at = now
            automation.next_run_at = compute_next_run(config, now)
            _record_run(db, automation, now, "success", summary)
            ran += 1
        except Exception as exc:  # noqa: BLE001 — one bad automation never aborts the rest
            logger.exception("Automation run failed (id=%s)", automation.id)
            # Still advance next_run_at so a hard-failing automation doesn't get
            # re-scanned every tick; the error is captured in the run row.
            automation.last_run_at = now
            automation.next_run_at = compute_next_run(config, now)
            _record_run(db, automation, now, "error", {}, error=str(exc))
            errored += 1

    db.commit()
    return {"due": len(due), "ran": ran, "skipped": skipped, "errored": errored}
