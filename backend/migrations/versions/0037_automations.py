"""CR-012: automations + automation_runs (Otomasyonlar — curated templates)

Revision ID: 0037_automations
Revises: 0036_landowner_payments
Create Date: 2026-06-21

Additive only — no backfill. Two new company-scoped tables backing the curated
automation templates: ``automations`` (a company's enabled+configured instance of
a template) and ``automation_runs`` (run history / audit). Both are RLS-isolated
to the owning company (a cron run for company A must never touch company B's data)
and soft-deletable via the shared timestamp/soft-delete columns. Existing
companies have no rows → zero behaviour change until a template is enabled.

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32)).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import create_index, create_policy, create_table, enable_rls

revision = "0037_automations"
down_revision = "0036_landowner_payments"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    create_table(
        "automations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("template_key", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index("ix_automations_company", "automations", ["company_id"])
    # Due-scan driver (§7): scheduled automations whose next_run_at <= now.
    create_index("ix_automations_next_run", "automations", ["next_run_at"])

    create_table(
        "automation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("automations.id"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("template_key", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), server_default="success", nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index("ix_automation_runs_automation", "automation_runs", ["automation_id"])
    create_index("ix_automation_runs_company", "automation_runs", ["company_id"])

    for table in ("automations", "automation_runs"):
        enable_rls(table)
        create_policy(f"{table}_company_isolation", table,
                      f"FOR ALL USING (company_id = {CURRENT_COMPANY})")
        create_policy(f"{table}_hide_deleted", table,
                      "FOR SELECT USING (is_deleted = false)")


def downgrade() -> None:
    for table in ("automation_runs", "automations"):
        op.execute(f"DROP POLICY IF EXISTS {table}_hide_deleted ON {table};")
        op.execute(f"DROP POLICY IF EXISTS {table}_company_isolation ON {table};")
    op.drop_index("ix_automation_runs_company", table_name="automation_runs")
    op.drop_index("ix_automation_runs_automation", table_name="automation_runs")
    op.drop_table("automation_runs")
    op.drop_index("ix_automations_next_run", table_name="automations")
    op.drop_index("ix_automations_company", table_name="automations")
    op.drop_table("automations")
