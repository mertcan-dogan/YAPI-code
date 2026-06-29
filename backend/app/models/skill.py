"""skills + skill_runs tables — saved AI "Beceri" (Skill) recipes (CR-044).

A **Skill** is a saved, named, reusable *deliverable recipe*: a free-form Turkish
``instruction`` plus the agent-compiled ``plan`` (a dashboard-shaped JSONB — the
SAME ``{format, title, widgets[], date_range?}`` shape a CR-034 pano uses) and an
output ``format`` (xlsx|pdf). The agent decides STRUCTURE only; every figure is
produced by the trusted engine (``run_spec``) at RUN time — the plan stores no
computed numbers (same no-fabrication invariant as the agent, CR-011). The plan is
saved and re-used on every run (reproducible month-to-month); editing the
instruction / "yeniden yorumla" recompiles it via the agent draft path.

``owner_id`` gates edit/delete; ``visibility`` ('private' by default) controls who
in the company may view/run it — mirrors Report/Dashboard. RLS / company scoping is
enforced in migration 0046; soft-delete via the shared mixin (id / created_at /
updated_at / is_deleted / deleted_at).

The ``schedule_*`` columns ship DORMANT here — CR-045 (Skills scheduling + notify)
bolts the existing Automation scheduler onto them, so it needs NO further migration.

A **SkillRun** is one execution: it records the produced file (the private
``documents``-bucket key + display name + format) and an ok|error status, powering
run history, the chat download card, the Oturum Çıktıları panel, and re-downloads.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID
from app.models.types import JSONB


class Skill(TimestampSoftDeleteMixin, Base):
    __tablename__ = "skills"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Ownership/edit gate — the user who may modify or delete this skill.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # The user's free-form, editable natural-language deliverable description.
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    # The agent-compiled runnable form: a dashboard-shaped spec
    # ``{format, title, widgets:[...], date_range?}``. Portable JSONB; defaults {}.
    # NOTE: server_default is the dialect-portable ``'{}'`` (not ``'{}'::jsonb``) so
    # the SQLite test create_all parses it; Postgres casts the literal to jsonb. The
    # prod default comes from migration 0046, which uses ``'{}'::jsonb``.
    plan: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    # xlsx | pdf — the produced file format.
    format: Mapped[str] = mapped_column(String(8), nullable=False, default="xlsx")
    # private | company — defaults to private (same model as Report/Dashboard).
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="private", server_default="private"
    )
    labels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- DORMANT schedule columns (CR-045 uses them; no further migration) --- #
    schedule_cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    schedule_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class SkillRun(TimestampSoftDeleteMixin, Base):
    __tablename__ = "skill_runs"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("skills.id"), nullable=False
    )
    run_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # ok | error
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="ok")
    # The PRIVATE ``documents``-bucket object key (company-scoped path) + display name.
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    format: Mapped[str | None] = mapped_column(String(8), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
