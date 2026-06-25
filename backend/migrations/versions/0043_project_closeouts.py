"""Project closeout lifecycle: project_closeouts table + its RLS policy

Revision ID: 0043_project_closeouts
Revises: 0042_invites
Create Date: 2026-06-25

Additive only — one new company-scoped table, ``project_closeouts``, backing the
Turkish acceptance lifecycle (Aktif → Geçici Kabul → Kesin Hesap → Kesin Kabul)
and the frozen "Proje Sonu Raporu". A row tracks one project through the stages;
at Kesin Hesap the rendered report dict is frozen into ``report_data`` (JSONB).
Reopening flips ``is_active`` to false (the row is KEPT for history); a later
re-close inserts a new active row. Existing companies have no rows → zero
behaviour change until a director starts a closeout.

RLS (post-0040 model)
---------------------
Isolation policy uses the per-request GUC ``app.current_company`` with WITH CHECK,
EXACTLY like the 0040 tables and the 0042 invites table — a director can only
read/write closeouts in their OWN company on the request (NOBYPASSRLS ``yapi_app``)
session. No ``*_hide_deleted`` policy (0040 dropped those; this table has no
is_deleted — history is via is_active). NO FORCE is left off to match every other
table (FORCE only affects the owner; the app role is not the owner).

GRANTS: like every additive table since the role cutover, request-session DML
grants for ``yapi_app`` come from the cluster's ``ALTER DEFAULT PRIVILEGES`` (a
one-time ops act applied when the role was created), so the owner-created table is
auto-granted SELECT/INSERT/UPDATE. We deliberately do NOT emit explicit GRANTs
here (neither 0040 nor 0042 does) — an explicit grant would fail local migration
validation where the ``yapi_app`` role does not exist.

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32)).
Migrations only run on Postgres (run_migrations skips non-Postgres URLs); the
SQLite test suite builds this table via Base.metadata.create_all instead, so the
Postgres-only RLS DDL below never reaches SQLite. The table create + index are
idempotent (the 0001 baseline's create_all already builds them on a fresh DB).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_index, create_policy, create_table, enable_rls

revision = "0043_project_closeouts"
down_revision = "0042_invites"
branch_labels = None
depends_on = None

# Per-request GUC — identical to 0040/0042. NULLIF(...,'') collapses an unset/empty
# value to NULL (fail-closed: no company context ⇒ zero rows).
GUC = "NULLIF(current_setting('app.current_company', true), '')::uuid"


def upgrade() -> None:
    create_table(
        "project_closeouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("stage", sa.String(20), nullable=True),
        sa.Column("gecici_kabul_date", sa.Date(), nullable=True),
        sa.Column("kesin_hesap_date", sa.Date(), nullable=True),
        sa.Column("kesin_kabul_date", sa.Date(), nullable=True),
        sa.Column("report_data", postgresql.JSONB(), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index(
        "ix_project_closeouts_company_project",
        "project_closeouts",
        ["company_id", "project_id"],
    )

    # Tenant isolation on the request (yapi_app) session — same shape as 0042.
    enable_rls("project_closeouts")
    op.execute("ALTER TABLE project_closeouts NO FORCE ROW LEVEL SECURITY;")
    create_policy(
        "project_closeouts_company_isolation",
        "project_closeouts",
        f"FOR ALL USING (company_id = {GUC}) WITH CHECK (company_id = {GUC})",
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS project_closeouts_company_isolation ON project_closeouts;")
    op.drop_index("ix_project_closeouts_company_project", table_name="project_closeouts")
    op.drop_table("project_closeouts")
