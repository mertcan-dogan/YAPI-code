"""fix RLS: remove FORCE so the backend service role can read; re-assert policies

Revision ID: 0005_fix_rls_no_force
Revises: 0004_cr001d_custom_categories
Create Date: 2025-06-07

Root cause of "data in DB but API returns empty":
  Migration 0002 applied FORCE ROW LEVEL SECURITY to every table. FORCE makes RLS
  apply even to the table owner / service role. The FastAPI backend connects to
  Postgres directly (not via Supabase PostgREST), so auth.uid() is NULL at the DB
  level, and the policy `company_id = (SELECT company_id FROM users WHERE
  id = auth.uid())` matches zero rows — every SELECT comes back empty.

Fix (aligns with PRD Section 2.4, which specified ENABLE only, not FORCE):
  - NO FORCE ROW LEVEL SECURITY on all tables, so the trusted backend service
    role bypasses RLS. Company isolation is still enforced in application code
    (Project.company_id == user.company_id + access checks) and RLS still governs
    any non-owner / anon connection.
  - Keep RLS ENABLED and idempotently re-assert every policy, so the policies are
    provably intact and correct after this migration.
"""
from alembic import op

revision = "0005_fix_rls_no_force"
down_revision = "0004_cr001d_custom_categories"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"

ALL_TABLES = [
    "companies",
    "users",
    "projects",
    "cost_entries",
    "client_invoices",
    "subcontractors",
    "equipment_log",
    "budget_line_items",
    "audit_log",
    "ai_alerts",
    "custom_cost_categories",
]

# Tables isolated by their own company_id column.
COMPANY_SCOPED_TABLES = [
    "users",
    "projects",
    "cost_entries",
    "client_invoices",
    "subcontractors",
    "equipment_log",
    "budget_line_items",
    "audit_log",
    "ai_alerts",
    "custom_cost_categories",
]

SOFT_DELETE_TABLES = [
    "users",
    "projects",
    "cost_entries",
    "client_invoices",
    "subcontractors",
    "equipment_log",
    "budget_line_items",
    "custom_cost_categories",
]


def upgrade() -> None:
    # 1) Keep RLS enabled but remove FORCE so the owner/service role bypasses it.
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")

    # 2) Re-assert the companies isolation policy (isolated by id).
    op.execute("DROP POLICY IF EXISTS companies_company_isolation ON companies;")
    op.execute(
        f"CREATE POLICY companies_company_isolation ON companies "
        f"FOR ALL USING (id = {CURRENT_COMPANY});"
    )

    # 3) Re-assert company isolation on every company-scoped table.
    for table in COMPANY_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_company_isolation ON {table};")
        op.execute(
            f"CREATE POLICY {table}_company_isolation ON {table} "
            f"FOR ALL USING (company_id = {CURRENT_COMPANY});"
        )

    # 4) Re-assert hide-deleted on soft-delete tables.
    for table in SOFT_DELETE_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_hide_deleted ON {table};")
        op.execute(
            f"CREATE POLICY {table}_hide_deleted ON {table} "
            f"FOR SELECT USING (is_deleted = false);"
        )

    # 5) Re-assert audit_log append-only protection.
    op.execute("DROP POLICY IF EXISTS audit_log_append_only_no_update ON audit_log;")
    op.execute("CREATE POLICY audit_log_append_only_no_update ON audit_log FOR UPDATE USING (false);")
    op.execute("DROP POLICY IF EXISTS audit_log_append_only_no_delete ON audit_log;")
    op.execute("CREATE POLICY audit_log_append_only_no_delete ON audit_log FOR DELETE USING (false);")


def downgrade() -> None:
    # Restore FORCE (reverts to the 0002/0004 behaviour).
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
