"""CR-044 — Skill RUN service: compile-plan → live data → file → store → signed URL.

The core of a Skill. Running a skill is **read-only** with respect to business
data and needs NO approval: it generates a file from live data, it does not mutate
any financial row (so the CR-011 invariant is untouched — see the no-fabrication
note below).

Pipeline (all company-scoped; ``company_id`` always from the authenticated user):
  1. Batch-render the plan's widgets through the SAME read-only path the dashboard
     ``/run`` endpoint uses (``run_spec`` per widget + dashboard-global merge). This
     is the SOLE source of every figure in the file.
  2. Build the file bytes via ``studio_export_dashboard`` (xlsx/pdf).
  3. Store the bytes in the PRIVATE ``documents`` bucket under a company-scoped key.
  4. Write a ``SkillRun`` row (ok|error) — the durable record.
  5. Return a short-lived **signed** download URL to the private object.

NO FABRICATION: the LLM never writes numbers into the file. Step 1 calls the
trusted engine; the agent's ``run_skill`` tool only triggers this service and
relays the resulting download URL — it produces no figures itself.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dashboard import Dashboard
from app.models.skill import Skill, SkillRun
from app.models.user import User
from app.responses import APIError
from app.services import storage
from app.services.studio.export import studio_export_dashboard

_EXT = {"xlsx": "xlsx", "pdf": "pdf"}
_MEDIA = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def _slug(name: str) -> str:
    """A filesystem/display-safe slug from a skill name (ASCII-ish, hyphenated)."""
    keep = [c if (c.isalnum() or c in " -_") else " " for c in (name or "").strip()]
    s = "".join(keep).strip().replace(" ", "-")
    while "--" in s:
        s = s.replace("--", "-")
    return s[:80] or "beceri"


def _plan_dashboard(plan: dict) -> Dashboard:
    """Build a TRANSIENT (never-persisted) Dashboard from a skill's compiled plan so
    the canonical dashboard batch-run path renders it unchanged. Not added to the
    session — purely a carrier of widgets + dashboard-global query context."""
    plan = plan or {}
    return Dashboard(
        title=plan.get("title") or "Beceri",
        widgets=plan.get("widgets") or [],
        date_range=plan.get("date_range"),
        comparison=plan.get("comparison"),
        filters=plan.get("filters"),
    )


def run_skill(db: Session, user: User, skill: Skill, *, signed_ttl: int | None = None) -> dict:
    """Execute a (already-loaded, viewable) skill for ``user`` → produce + store the
    file, write a ``SkillRun``, and return ``{run_id, file_name, format, download_url}``.

    Read-only over business data; ``company_id`` comes from ``user``. On a render/
    export/storage failure an ``error`` SkillRun is recorded (durable run history)
    and a clean ``APIError`` is raised."""
    # Local import: reuse the canonical dashboard batch-run (run_spec per widget +
    # global merge + report-widget viewability). Function-local to avoid any
    # api<->service import-order coupling at module load.
    from app.api.studio import _run_dashboard_batch

    fmt = skill.format if skill.format in _EXT else "xlsx"
    ext = _EXT[fmt]
    file_name = f"{_slug(skill.name)}.{ext}"
    plan = skill.plan if isinstance(skill.plan, dict) else {}

    try:
        deck = _plan_dashboard(plan)
        results = _run_dashboard_batch(db, user, deck)  # SOLE figure source
        resp = studio_export_dashboard(deck.widgets or [], results, deck.title, fmt)
        data = bytes(resp.body)  # studio_export_dashboard returns a Response
        if not data:
            raise APIError(422, "NO_DATA", "Dışa aktarılacak veri yok")
        path = f"{user.company_id}/skills/{skill.id}/{uuid.uuid4().hex}.{ext}"
        storage.upload_bytes(path, data, _MEDIA[fmt])
    except APIError as exc:
        _record_error(db, user, skill, fmt, exc.message)
        raise
    except Exception as exc:  # noqa: BLE001 — any render/export bug becomes a clean run error
        _record_error(db, user, skill, fmt, "Beceri çalıştırılırken bir hata oluştu")
        raise APIError(500, "SKILL_RUN_ERROR", "Beceri çalıştırılamadı") from exc

    run = SkillRun(
        company_id=user.company_id,
        skill_id=skill.id,
        run_by=user.id,
        status="ok",
        file_path=path,
        file_name=file_name,
        format=fmt,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    download_url = storage.signed_url(
        path, company_id=user.company_id,
        expires_in=signed_ttl or storage.DEFAULT_SIGNED_URL_TTL,
        download_name=file_name,
    )
    return {
        "run_id": str(run.id),
        "skill_id": str(skill.id),
        "file_name": file_name,
        "format": fmt,
        "download_url": download_url,
    }


def _record_error(db: Session, user: User, skill: Skill, fmt: str, message: str) -> None:
    """Persist an ``error`` SkillRun so a failed run still appears in history."""
    try:
        db.rollback()
        db.add(SkillRun(
            company_id=user.company_id,
            skill_id=skill.id,
            run_by=user.id,
            status="error",
            format=fmt,
            error=(message or "")[:1000],
        ))
        db.commit()
    except Exception:  # never let error-bookkeeping mask the original failure
        db.rollback()


# --------------------------------------------------------------------------- #
# Agent tool entry point — run_skill(skill_id)
# --------------------------------------------------------------------------- #
def _viewable_skill(db: Session, user: User, skill_id) -> Skill | None:
    """The skill ``user`` may VIEW/RUN: own (any visibility) + company-visible,
    company-scoped, not soft-deleted. None on cross-company / private-stranger /
    missing / malformed id (the caller turns None into a clean 404 / tool error)."""
    from sqlalchemy import or_
    try:
        sid = skill_id if isinstance(skill_id, uuid.UUID) else uuid.UUID(str(skill_id))
    except (ValueError, TypeError, AttributeError):
        return None
    return db.execute(
        select(Skill).where(
            Skill.id == sid,
            Skill.company_id == user.company_id,
            Skill.is_deleted.is_(False),
            or_(Skill.owner_id == user.id, Skill.visibility == "company"),
        )
    ).scalar_one_or_none()


def run_skill_tool(db: Session, company_id, user_id, skill_id) -> dict:
    """Agent ``run_skill`` tool: load the viewable skill (company-scoped), run it,
    and return a result the chat renders as a download card. Read-only / no approval.
    Returns ``{error}`` on a bad id / not-viewable skill (the agent recovers)."""
    if user_id is None:
        return {"error": "Bu eylem için oturum bağlamı gerekli."}
    user = db.get(User, user_id)
    if user is None:
        return {"error": "Oturum bağlamı çözümlenemedi."}
    skill = _viewable_skill(db, user, skill_id)
    if skill is None:
        return {"error": "Beceri bulunamadı (kimlik geçersiz veya erişiminiz yok)."}
    try:
        res = run_skill(db, user, skill)
    except APIError as exc:
        return {"error": exc.message}

    pa = {
        "kind": "run_result",
        "kind_label": "Üretilen Dosya",
        "file_name": res["file_name"],
        "format": res["format"],
        "download_url": res["download_url"],
        "run_id": res["run_id"],
        "skill_id": res["skill_id"],
        "skill_name": skill.name,
    }
    return {
        "ok": True,
        "ran": True,
        "message": (
            f"«{skill.name}» çalıştırıldı; dosya üretildi ve Oturum Çıktıları'na "
            "kaydedildi. İndirme bağlantısı kart olarak gösterildi."
        ),
        "file_name": res["file_name"],
        "download_url": res["download_url"],
        "proposed_action": pa,
    }
