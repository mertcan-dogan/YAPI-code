"""Report Studio: reports table + its RLS policy

Revision ID: 0044_reports
Revises: 0043_project_closeouts
Create Date: 2026-06-26

Additive only — one new company-scoped table, ``reports``, backing the Report
Studio (CR-033). A row is pure metadata: a saved CR-032 report ``spec`` (JSONB)
plus ownership/presentation fields. No computed results are stored — the spec is
re-executed by the engine on demand. ``owner_id`` gates edit/delete; ``visibility``
('private' by default) controls who in the company may view it. Existing companies
have no rows → zero behaviour change until a user saves a report.

RLS (post-0040 model)
---------------------
Isolation policy uses the per-request GUC ``app.current_company`` with WITH CHECK,
EXACTLY like the 0040 tables and the 0043 project_closeouts table — a user can only
read/write reports in their OWN company on the request (NOBYPASSRLS ``yapi_app``)
session. No ``*_hide_deleted`` policy (0040 dropped those). NO FORCE is left off to
match every other table (FORCE only affects the owner; the app role is not the
owner).

GRANTS: like every additive table since the role cutover, request-session DML
grants for ``yapi_app`` come from the cluster's ``ALTER DEFAULT PRIVILEGES`` (a
one-time ops act applied when the role was created), so the owner-created table is
auto-granted SELECT/INSERT/UPDATE. We deliberately do NOT emit explicit GRANTs here
(neither 0040 nor 0043 does) — an explicit grant would fail local migration
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

revision = "0044_reports"
down_revision = "0043_project_closeouts"
branch_labels = None
depends_on = None

# Per-request GUC — identical to 0040/0043. NULLIF(...,'') collapses an unset/empty
# value to NULL (fail-closed: no company context ⇒ zero rows).
GUC = "NULLIF(current_setting('app.current_company', true), '')::uuid"


def upgrade() -> None:
    create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("visibility", sa.String(16), server_default="private", nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index(
        "ix_reports_company_owner",
        "reports",
        ["company_id", "owner_id"],
    )

    # Tenant isolation on the request (yapi_app) session — same shape as 0043.
    enable_rls("reports")
    op.execute("ALTER TABLE reports NO FORCE ROW LEVEL SECURITY;")
    create_policy(
        "reports_company_isolation",
        "reports",
        f"FOR ALL USING (company_id = {GUC}) WITH CHECK (company_id = {GUC})",
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS reports_company_isolation ON reports;")
    op.drop_index("ix_reports_company_owner", table_name="reports")
    op.drop_table("reports")
