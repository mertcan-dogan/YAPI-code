"""Skills (Beceriler): skills + skill_runs tables + their RLS policies (CR-044)

Revision ID: 0046_skills
Revises: 0045_dashboards
Create Date: 2026-06-29

Additive only — two new company-scoped tables backing the "Uygulamalar" (Skills)
surface (CR-044). A ``skills`` row is a saved AI deliverable recipe: a free-form
``instruction`` + the agent-compiled ``plan`` (a dashboard-shaped JSONB of CR-032
widget specs) + an output ``format`` (xlsx|pdf). It stores NO computed numbers —
each run re-executes the plan through the trusted engine (``run_spec``) and writes
a ``skill_runs`` row recording the produced file (the private ``documents``-bucket
key + name + status). ``owner_id`` gates edit/delete; ``visibility`` ('private' by
default) controls who in the company may view/run it. Existing companies have no
rows → zero behaviour change until a user saves a skill.

The ``schedule_cron`` / ``next_run_at`` / ``schedule_enabled`` columns ship DORMANT:
CR-045 (Skills scheduling + notify) bolts the existing Automation scheduler onto
them, so it needs NO further migration.

RLS (post-0040 model)
---------------------
Isolation policy uses the per-request GUC ``app.current_company`` with WITH CHECK,
EXACTLY like the 0040/0044/0045 tables — a user can only read/write rows in their
OWN company on the request (NOBYPASSRLS ``yapi_app``) session. No
``*_hide_deleted`` policy (0040 dropped those). NO FORCE is left off to match every
other table (FORCE only affects the owner; the app role is not the owner).

GRANTS: like every additive table since the role cutover, request-session DML
grants for ``yapi_app`` come from the cluster's ``ALTER DEFAULT PRIVILEGES`` (a
one-time ops act), so the owner-created tables are auto-granted. We deliberately do
NOT emit explicit GRANTs here (neither 0040/0044/0045 does) — an explicit grant
would fail local migration validation where ``yapi_app`` does not exist.

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32)).
Migrations only run on Postgres (run_migrations skips non-Postgres URLs); the
SQLite test suite builds these tables via Base.metadata.create_all instead, so the
Postgres-only RLS DDL below never reaches SQLite. The table creates + indexes are
idempotent (the 0001 baseline's create_all already builds them on a fresh DB).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_index, create_policy, create_table, enable_rls

revision = "0046_skills"
down_revision = "0045_dashboards"
branch_labels = None
depends_on = None

# Per-request GUC — identical to 0040/0044/0045. NULLIF(...,'') collapses an
# unset/empty value to NULL (fail-closed: no company context ⇒ zero rows).
GUC = "NULLIF(current_setting('app.current_company', true), '')::uuid"


def upgrade() -> None:
    # --- skills --------------------------------------------------------------- #
    create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("plan", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("visibility", sa.String(16), server_default="private", nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=True),
        # DORMANT schedule columns (CR-045, no further migration).
        sa.Column("schedule_cron", sa.String(120), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schedule_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index(
        "ix_skills_company_owner",
        "skills",
        ["company_id", "owner_id"],
    )

    # --- skill_runs ----------------------------------------------------------- #
    create_table(
        "skill_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("run_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("format", sa.String(8), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index(
        "ix_skill_runs_company_skill",
        "skill_runs",
        ["company_id", "skill_id"],
    )

    # Tenant isolation on the request (yapi_app) session — same shape as 0045.
    enable_rls("skills")
    op.execute("ALTER TABLE skills NO FORCE ROW LEVEL SECURITY;")
    create_policy(
        "skills_company_isolation",
        "skills",
        f"FOR ALL USING (company_id = {GUC}) WITH CHECK (company_id = {GUC})",
    )

    enable_rls("skill_runs")
    op.execute("ALTER TABLE skill_runs NO FORCE ROW LEVEL SECURITY;")
    create_policy(
        "skill_runs_company_isolation",
        "skill_runs",
        f"FOR ALL USING (company_id = {GUC}) WITH CHECK (company_id = {GUC})",
    )


def downgrade() -> None:
    # Reverse order — drop skill_runs (FK → skills) before skills.
    op.execute("DROP POLICY IF EXISTS skill_runs_company_isolation ON skill_runs;")
    op.drop_index("ix_skill_runs_company_skill", table_name="skill_runs")
    op.drop_table("skill_runs")

    op.execute("DROP POLICY IF EXISTS skills_company_isolation ON skills;")
    op.drop_index("ix_skills_company_owner", table_name="skills")
    op.drop_table("skills")
