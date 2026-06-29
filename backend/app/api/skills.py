"""CR-044 — Skills (Beceriler / "Uygulamalar") API: CRUD + run + re-download.

Every endpoint is ``CurrentUser``-gated and company-scoped: ``company_id`` /
``owner_id`` ALWAYS come from the authenticated user, NEVER from the request body.
A Skill is the user's free-form ``instruction`` + the agent-compiled ``plan`` (a
dashboard-shaped spec) + an output ``format``. Saved skills are soft-deleted;
``visibility`` is "private" (owner-only) or "company" (all same-company users may
view/run). Edit/delete is owner-or-director only (the CR-033 ``_viewable`` /
``_editable`` pattern).

Creating a skill is the **user's own action** (like CR-039 OLUŞTUR): the agent only
DRAFTS (``propose_skill`` writes nothing); the row is created here, by the caller.
Running a skill (``POST /skills/{id}/run``) is **read-only** over business data and
needs NO approval — it generates a file from live data via the trusted engine (see
``services/skills.py``); the figures are never written by the model.
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.constants import ROLE_DIRECTOR
from app.db import get_db
from app.deps import CurrentUser
from app.models.skill import Skill, SkillRun
from app.responses import APIError, success
from app.schemas.skill import (
    SkillCreate,
    SkillListItem,
    SkillOut,
    SkillRunOut,
    SkillRunSummary,
    SkillUpdate,
)
from app.services import skills as skills_service
from app.services.studio import creators

router = APIRouter(tags=["skills"])

_VALID_FORMATS = ("xlsx", "pdf")


# --------------------------------------------------------------------------- #
# Serialization + access helpers (mirror api/studio.py)
# --------------------------------------------------------------------------- #
def _run_summary(run: SkillRun | None) -> SkillRunSummary | None:
    """CR-044.1 — the embeddable latest-run summary (or None)."""
    if run is None:
        return None
    return SkillRunSummary(
        run_id=run.id, run_at=run.run_at, file_name=run.file_name, status=run.status
    )


def _latest_ok_run(db: Session, company_id, skill_id) -> SkillRun | None:
    """The most recent SUCCESSFUL (downloadable) run of a skill, company-scoped."""
    return db.execute(
        select(SkillRun)
        .where(
            SkillRun.company_id == company_id,
            SkillRun.skill_id == skill_id,
            SkillRun.is_deleted.is_(False),
            SkillRun.status == "ok",
        )
        .order_by(SkillRun.run_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _skill_out(skill: Skill, user, db: Session) -> dict:
    last_run = _latest_ok_run(db, user.company_id, skill.id)
    return SkillOut(
        id=skill.id,
        name=skill.name,
        instruction=skill.instruction,
        plan=skill.plan or {},
        format=skill.format,
        visibility=skill.visibility,
        labels=skill.labels,
        owner_id=skill.owner_id,
        created_by=skill.created_by,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
        is_owner=(skill.owner_id == user.id),
        last_run=_run_summary(last_run),
    ).model_dump(mode="json")


def _viewable_q(user):
    """Skills the user may VIEW/RUN: own (any visibility) + company-visible. Always
    company-scoped and excludes soft-deleted rows. Another user's ``private`` skill
    is simply not selected — no existence leak."""
    return select(Skill).where(
        Skill.company_id == user.company_id,
        Skill.is_deleted.is_(False),
        or_(Skill.owner_id == user.id, Skill.visibility == "company"),
    )


def _get_viewable(db: Session, user, skill_id: uuid.UUID) -> Skill:
    skill = db.execute(_viewable_q(user).where(Skill.id == skill_id)).scalar_one_or_none()
    if skill is None:
        raise APIError(404, "NOT_FOUND", "Beceri bulunamadı")
    return skill


def _get_editable(db: Session, user, skill_id: uuid.UUID) -> Skill:
    """Skills the user may EDIT/DELETE. Fetch predicate: in-company, not deleted,
    and (owner OR company-visible OR director). Then gate: a non-director, non-owner
    is forbidden (403). Net effect — private+stranger → 404 (invisible),
    company+stranger-non-director → 403, owner/director → ok."""
    stmt = select(Skill).where(
        Skill.id == skill_id,
        Skill.company_id == user.company_id,
        Skill.is_deleted.is_(False),
    )
    if user.role != ROLE_DIRECTOR:
        stmt = stmt.where(or_(Skill.owner_id == user.id, Skill.visibility == "company"))
    skill = db.execute(stmt).scalar_one_or_none()
    if skill is None:
        raise APIError(404, "NOT_FOUND", "Beceri bulunamadı")
    if user.role != ROLE_DIRECTOR and skill.owner_id != user.id:
        raise APIError(403, "FORBIDDEN", "Bu beceriyi düzenleme yetkiniz yok")
    return skill


def _validate_plan(db: Session, user, plan) -> None:
    """Structurally validate a compiled plan before persisting — a dashboard-shaped
    ``{widgets:[...]}`` whose widget specs are checked against the catalog (the SAME
    validator dashboards use). Never trust a client-supplied plan: re-validate here
    so a hand-rolled POST can't store junk or an out-of-catalog metric. Raises
    ``APIError(422)`` on any violation."""
    if not isinstance(plan, dict):
        raise APIError(422, "VALIDATION_ERROR", "Beceri planı bir nesne olmalı", field="plan")
    widgets = plan.get("widgets")
    if not isinstance(widgets, list) or not widgets:
        raise APIError(422, "VALIDATION_ERROR", "Beceri planı en az bir widget içermeli", field="plan")
    # Raises APIError(422) on a bad widget / out-of-catalog spec / dup id / cap.
    creators.validate_widgets(db, user.company_id, user.id, widgets)


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
@router.get("/skills")
def list_skills(user: CurrentUser, q: str | None = None, db: Session = Depends(get_db)):
    """Saved skills the user may view, newest-edited first. Optional ``q`` does a
    case-insensitive name contains-match. Each row carries ``last_run`` (the most
    recent SUCCESSFUL run — for "Son çalıştırma" + an immediate re-download İndir)
    and ``last_run_at`` (kept for back-compat + sort)."""
    # Latest SUCCESSFUL run per skill (company-scoped). Fetched newest-first and
    # de-duped in Python (portable: SQLite + Postgres) → {skill_id: SkillRun}.
    latest_run: dict = {}
    for run in db.execute(
        select(SkillRun)
        .where(
            SkillRun.company_id == user.company_id,
            SkillRun.is_deleted.is_(False),
            SkillRun.status == "ok",
        )
        .order_by(SkillRun.run_at.desc())
    ).scalars():
        latest_run.setdefault(run.skill_id, run)
    stmt = _viewable_q(user)
    if q:
        stmt = stmt.where(Skill.name.ilike(f"%{q}%"))
    rows = db.execute(stmt.order_by(Skill.updated_at.desc())).scalars().all()
    items = [
        SkillListItem(
            id=s.id,
            name=s.name,
            format=s.format,
            visibility=s.visibility,
            owner_id=s.owner_id,
            updated_at=s.updated_at,
            labels=s.labels,
            last_run_at=(latest_run[s.id].run_at if s.id in latest_run else None),
            last_run=_run_summary(latest_run.get(s.id)),
        ).model_dump(mode="json")
        for s in rows
    ]
    return success(items)


@router.post("/skills")
def create_skill(body: SkillCreate, user: CurrentUser, db: Session = Depends(get_db)):
    """Save a new skill. The compiled ``plan`` is re-validated against the catalog
    (never trust the client). ``company_id`` / ``owner_id`` / ``created_by`` come
    from the authenticated user — never the body. This is the user's own create
    (CR-039 OLUŞTUR-style); the agent only drafts."""
    _validate_plan(db, user, body.plan)
    skill = Skill(
        company_id=user.company_id,
        owner_id=user.id,
        created_by=user.id,
        name=body.name,
        instruction=body.instruction,
        plan=body.plan,
        format=body.format if body.format in _VALID_FORMATS else "xlsx",
        visibility=body.visibility,
        labels=body.labels,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return success(_skill_out(skill, user, db))


@router.get("/skills/{skill_id}")
def get_skill(skill_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    skill = _get_viewable(db, user, skill_id)
    return success(_skill_out(skill, user, db))


@router.put("/skills/{skill_id}")
def update_skill(
    skill_id: uuid.UUID, body: SkillUpdate, user: CurrentUser, db: Session = Depends(get_db)
):
    """Update a skill (owner-or-director). Editing the instruction/plan is how a
    recompiled plan ("yeniden yorumla") is saved. If ``plan`` is provided it is
    re-validated against the catalog."""
    skill = _get_editable(db, user, skill_id)
    data = body.model_dump(exclude_unset=True)
    if "plan" in data and data["plan"] is not None:
        _validate_plan(db, user, data["plan"])
    for field in ("name", "instruction", "plan", "format", "visibility", "labels"):
        if field in data and data[field] is not None:
            setattr(skill, field, data[field])
    db.commit()
    db.refresh(skill)
    return success(_skill_out(skill, user, db))


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """Soft-delete a skill (owner-or-director). Past run rows/files are left intact."""
    skill = _get_editable(db, user, skill_id)
    skill.is_deleted = True
    db.commit()
    return success({"ok": True})


@router.get("/skills/{skill_id}/runs")
def list_skill_runs(skill_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """Run history for a viewable skill, newest first."""
    _get_viewable(db, user, skill_id)  # 404 if not viewable
    rows = db.execute(
        select(SkillRun)
        .where(
            SkillRun.company_id == user.company_id,
            SkillRun.skill_id == skill_id,
            SkillRun.is_deleted.is_(False),
        )
        .order_by(SkillRun.run_at.desc())
    ).scalars().all()
    return success([SkillRunOut.model_validate(r).model_dump(mode="json") for r in rows])


# --------------------------------------------------------------------------- #
# Run (the core) — read-only, no approval
# --------------------------------------------------------------------------- #
@router.post("/skills/{skill_id}/run")
def run_skill_endpoint(skill_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """Run a skill → generate a file from LIVE data, store it privately, write a
    SkillRun, and return a short-lived signed download URL. Read-only over business
    data; no approval needed. Cross-company / private-stranger id → 404."""
    skill = _get_viewable(db, user, skill_id)
    result = skills_service.run_skill(db, user, skill)
    return success(result)


@router.post("/skills/runs/{run_id}/download")
def redownload_skill_run(run_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """Re-issue a short-lived signed URL for a past run's file. Company-scoped AND
    skill-viewable-scoped: a run whose skill the caller can't view (another tenant's,
    or a stranger's private skill) → 404; ``storage.signed_url`` additionally refuses
    to sign any path outside the caller's company folder."""
    run = db.execute(
        select(SkillRun).where(
            SkillRun.id == run_id,
            SkillRun.company_id == user.company_id,
            SkillRun.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if run is None or run.status != "ok" or not run.file_path:
        raise APIError(404, "NOT_FOUND", "Dosya bulunamadı")
    # The run's skill must still be viewable by this user (respect private skills).
    _get_viewable(db, user, run.skill_id)
    url = skills_service.storage.signed_url(
        run.file_path, company_id=user.company_id, download_name=run.file_name
    )
    return success({"download_url": url, "file_name": run.file_name, "format": run.format})
