"""CR-040: real DB-level tenant isolation via a per-request GUC + WITH CHECK

Revision ID: 0040_rls_guc_isolation
Revises: 0039_extraction_confidence
Create Date: 2026-06-24

WHY
---
Until now RLS was effectively cosmetic. The backend connects to Postgres as the
Supabase service_role (which has BYPASSRLS), and migration 0005 set NO FORCE, so
the owner/service role bypassed every policy. Tenant isolation rested ENTIRELY on
application-code ``company_id`` filters — a single missing filter would silently
leak financial data across companies.

This migration makes RLS *real* together with two out-of-band changes (see the
0040 wiring item + ops walkthrough):
  1. The app connects as a dedicated ``yapi_app`` role that is NOBYPASSRLS, so
     policies actually apply to request traffic. (Role is created in Supabase ops,
     NOT here — it needs a secret password and is a one-time cluster act.)
  2. Each request sets ``app.current_company`` to the caller's company_id on its
     DB session; this migration's policies read that GUC.

WHAT CHANGES vs 0005/0035-style policies
----------------------------------------
  * Policy predicate moves from ``auth.uid()`` (always NULL on a direct backend
    connection) to the request GUC ``app.current_company``.
  * Adds ``WITH CHECK`` to every isolation policy so a row can no longer be
    INSERTed/UPDATEd *into another company* (0005 used USING only → guarded reads
    and row visibility, but not the written company_id).
  * Covers every company-scoped table (27) + ``companies``, not just the 11 from
    0005 — newer tables (vendors, unit_sales, automations, …) are folded in.
  * DROPS the legacy ``*_hide_deleted`` policies. As separate permissive policies
    they OR with the FOR ALL isolation policy on SELECT — i.e.
    ``(company_id = GUC) OR (is_deleted = false)`` — which, once RLS is actually
    enforced under the app role, would expose every company's non-deleted rows.
    Soft-delete hiding already happens in app code (167 ``is_deleted=false``
    filters; the app never reads deleted rows), so this is a no-behaviour-change
    leak fix. (downgrade re-creates them.)

FORCE stays OFF on purpose. FORCE only matters for the table *owner*; the app
role is not the owner, so plain ENABLE + a NOBYPASSRLS app role enforces RLS on
request traffic while the owner/migrations/cron keep full access. Flipping FORCE
would re-break migrations for zero security gain.

GUC CONTRACT (enforced by the wiring item): ``app.current_company`` is set to a
real uuid string OR left unset — NEVER the empty string. The policy uses
``NULLIF(current_setting('app.current_company', true), '')::uuid`` so that an
unset GUC (and, defensively, an empty one) yields NULL → ``company_id = NULL`` is
NULL → zero rows. Fail-closed: no company context means no data.

DOWNGRADE fully reverts to the pre-0040 ``auth.uid()`` policies (no WITH CHECK),
so combined with flipping the app's DATABASE_URL back to service_role this
returns behaviour to exactly today's. NO FORCE is left as-is (it already was).
"""
from alembic import op

from migrations.idempotent import create_policy, enable_rls, has_table

revision = "0040_rls_guc_isolation"
down_revision = "0039_extraction_confidence"
branch_labels = None
depends_on = None

# Per-request GUC. NULLIF(...,'') makes an unset OR empty value collapse to NULL
# (fail-closed) instead of raising on ''::uuid. The wiring must set a real uuid or
# leave it unset — never ''.
GUC = "NULLIF(current_setting('app.current_company', true), '')::uuid"

# Pre-0040 predicate, restored on downgrade.
AUTH_UID_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"

# Every table isolated by its own company_id column (verified against app/models).
# fx_rates is intentionally excluded (global reference data, no company_id).
COMPANY_SCOPED_TABLES = [
    "users",
    "projects",
    "project_units",
    "project_milestones",
    "cost_entries",
    "client_invoices",
    "subcontractors",
    "equipment_log",
    "budget_line_items",
    "custom_budget_templates",
    "custom_cost_categories",
    "variations",
    "kpi_snapshots",
    "notifications",
    "approval_requests",
    "audit_log",
    "ai_alerts",
    "ai_conversations",
    "ai_query_log",
    "ai_feedback",
    "vendors",
    "vendor_aliases",
    "workspace_items",
    "unit_sales",
    "landowner_payments",
    "automations",
    "automation_runs",
]

# Subset that has an is_deleted column (mixin OR declared manually on
# custom_budget_templates / custom_cost_categories). The four WITHOUT is_deleted —
# audit_log, ai_alerts, ai_query_log, ai_feedback — are deliberately absent.
SOFT_DELETE_TABLES = [
    "users",
    "projects",
    "project_units",
    "project_milestones",
    "cost_entries",
    "client_invoices",
    "subcontractors",
    "equipment_log",
    "budget_line_items",
    "custom_budget_templates",
    "custom_cost_categories",
    "variations",
    "kpi_snapshots",
    "notifications",
    "approval_requests",
    "ai_conversations",
    "vendors",
    "vendor_aliases",
    "workspace_items",
    "unit_sales",
    "landowner_payments",
    "automations",
    "automation_runs",
]


def upgrade() -> None:
    # 1) companies — isolated by its own id (not company_id). USING + WITH CHECK.
    enable_rls("companies")
    op.execute("ALTER TABLE companies NO FORCE ROW LEVEL SECURITY;")
    create_policy(
        "companies_company_isolation",
        "companies",
        f"FOR ALL USING (id = {GUC}) WITH CHECK (id = {GUC})",
    )

    # 2) Every company-scoped table — read+write isolation keyed off the GUC.
    for table in COMPANY_SCOPED_TABLES:
        enable_rls(table)
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        create_policy(
            f"{table}_company_isolation",
            table,
            f"FOR ALL USING (company_id = {GUC}) WITH CHECK (company_id = {GUC})",
        )

    # 3) Drop the legacy *_hide_deleted policies. As separate PERMISSIVE policies
    #    they OR with company_isolation (FOR ALL, which also covers SELECT):
    #    on SELECT the effective predicate becomes
    #        (company_id = GUC) OR (is_deleted = false)
    #    — harmless while RLS was bypassed (NO FORCE + service_role), but once the
    #    NOBYPASSRLS app role makes RLS real it would expose EVERY company's
    #    non-deleted rows: a cross-tenant LEAK. Soft-delete hiding is already done
    #    authoritatively in application code (167 is_deleted=false query filters)
    #    and the app never SELECTs deleted rows, so dropping these closes the leak
    #    with zero behaviour change. (downgrade re-creates them.)
    for table in SOFT_DELETE_TABLES:
        if has_table(table):
            op.execute(f"DROP POLICY IF EXISTS {table}_hide_deleted ON {table};")

    # 4) audit_log append-only guards — preserved exactly as 0005 created them.
    #    NOTE: as permissive FOR UPDATE/DELETE USING(false) they OR with
    #    company_isolation, so they do NOT actually block writes (effective:
    #    company_id=GUC OR false). They are kept unchanged (no leak — false adds
    #    nothing cross-company) to stay scoped to tenant isolation; making audit
    #    truly append-only (RESTRICTIVE) is a separate, optional follow-up.
    create_policy("audit_log_append_only_no_update", "audit_log", "FOR UPDATE USING (false)")
    create_policy("audit_log_append_only_no_delete", "audit_log", "FOR DELETE USING (false)")


def downgrade() -> None:
    # Restore the pre-0040 auth.uid()-based policies (USING only, no WITH CHECK).
    # Re-create over the GUC variants via drop-then-create. NO FORCE is unchanged.
    create_policy(
        "companies_company_isolation",
        "companies",
        f"FOR ALL USING (id = {AUTH_UID_COMPANY})",
    )
    for table in COMPANY_SCOPED_TABLES:
        create_policy(
            f"{table}_company_isolation",
            table,
            f"FOR ALL USING (company_id = {AUTH_UID_COMPANY})",
        )
    # Restore the *_hide_deleted policies dropped on upgrade, so downgrade returns
    # the policy set to exactly its pre-0040 shape.
    for table in SOFT_DELETE_TABLES:
        create_policy(
            f"{table}_hide_deleted",
            table,
            "FOR SELECT USING (is_deleted = false)",
        )
    # audit append-only policies are identical pre/post — leave them.
