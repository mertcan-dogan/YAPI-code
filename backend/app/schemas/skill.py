"""CR-044 — Skills (Beceriler) persistence schemas.

A saved Skill is the user's free-form ``instruction`` + the agent-compiled
``plan`` (a dashboard-shaped spec) + an output ``format``. The ``format`` and
``visibility`` ``Literal``s are defense-in-depth: anything else (e.g. "csv",
"team", or garbage) is rejected with 422 at the Pydantic layer, never reaching the
DB. ``is_owner`` on ``SkillOut`` is filled by the endpoint (``owner_id == user.id``);
it is not a column. ``plan`` is validated structurally by the endpoint
(``creators.validate_widgets``) before persist — the schema only enforces it is an
object.
"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SkillRunSummary(BaseModel):
    """CR-044.1 — the latest run of a skill, embedded on Skill responses so the
    Uygulamalar list/detail can show "Son çalıştırma" + a re-download İndir without
    a second request. ``run_id`` is the SkillRun id (re-sign via
    ``POST /skills/runs/{run_id}/download``)."""

    run_id: uuid.UUID
    run_at: datetime
    file_name: str | None = None
    status: str


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1)
    plan: dict
    format: Literal["xlsx", "pdf"] = "xlsx"
    visibility: Literal["private", "company"] = "private"
    labels: list[str] | None = None


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    instruction: str | None = Field(default=None, min_length=1)
    plan: dict | None = None
    format: Literal["xlsx", "pdf"] | None = None
    visibility: Literal["private", "company"] | None = None
    labels: list[str] | None = None


class SkillOut(ORMModel):
    id: uuid.UUID
    name: str
    instruction: str
    plan: dict
    format: str
    visibility: str
    labels: list[str] | None = None
    owner_id: uuid.UUID
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    is_owner: bool
    # CR-044.1 — the latest successful run (or null), for re-download from detail.
    last_run: SkillRunSummary | None = None


class SkillListItem(BaseModel):
    """Lightweight row for the Uygulamalar list — no full plan, just the picker
    preview + the last-run summary (for "Son çalıştırma" + re-download)."""

    id: uuid.UUID
    name: str
    format: str
    visibility: str
    owner_id: uuid.UUID
    updated_at: datetime
    labels: list[str] | None = None
    last_run_at: datetime | None = None
    # CR-044.1 — the latest successful run (or null), so a list row offers İndir
    # immediately on load. ``last_run_at`` is kept for back-compat + sort.
    last_run: SkillRunSummary | None = None


class SkillRunOut(ORMModel):
    id: uuid.UUID
    skill_id: uuid.UUID
    status: str
    file_name: str | None = None
    format: str | None = None
    run_at: datetime
    error: str | None = None
    run_by: uuid.UUID | None = None
