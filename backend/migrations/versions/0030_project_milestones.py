"""CR-019-A: project_milestones (weighted schedule milestones)

Revision ID: 0030_project_milestones
Revises: 0029_financing_settings
Create Date: 2026-06-17

Additive only — no backfill. The new ``project_milestones`` table adds the
SCHEDULE lane (weighted milestones, optionally grouped by a ``stage`` label,
with deadlines). Existing projects simply have no rows, so there is zero
behavior change until used. Company-scoped + RLS, mirroring project_units (0027),
with a composite ``(company_id, project_id)`` index per CR-019 §0.0.3.

SEPARATE LANES (CR-019 §0.2): milestones are schedule-only — they never touch
billing/margin/forecast money figures.

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32) — the
CR-007 0021 trap). "0030_project_milestones" is 23 chars.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_index, create_policy, create_table, enable_rls

revision = "0030_project_milestones"
down_revision = "0029_financing_settings"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    create_table(
        "project_milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("stage", sa.String(100), nullable=True),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("weight", sa.Numeric(10, 2), server_default="1", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("completed_date", sa.Date(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Composite index on (company_id, project_id) — CR-019 §0.0.3 / §1.1.
    create_index("ix_project_milestones_company_project", "project_milestones", ["company_id", "project_id"])

    # RLS parity (defence in depth), mirroring project_units (0027).
    enable_rls("project_milestones")
    create_policy("project_milestones_company_isolation", "project_milestones",
                  f"FOR ALL USING (company_id = {CURRENT_COMPANY})")
    create_policy("project_milestones_hide_deleted", "project_milestones",
                  "FOR SELECT USING (is_deleted = false)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS project_milestones_hide_deleted ON project_milestones;")
    op.execute("DROP POLICY IF EXISTS project_milestones_company_isolation ON project_milestones;")
    op.drop_index("ix_project_milestones_company_project", table_name="project_milestones")
    op.drop_table("project_milestones")
