"""enable Row-Level Security on every tenant table (Section 2.4)

Revision ID: 0002_enable_rls
Revises: 0001_initial_schema
Create Date: 2025-06-05

A company must never access another company's data. RLS is enforced at the
database level. The current company is resolved via:
    (SELECT company_id FROM users WHERE id = auth.uid())

For the companies table itself, isolation is by id (not company_id).
audit_log additionally blocks UPDATE/DELETE (append-only, Section 8.2).
"""
from alembic import op

from migrations.idempotent import create_policy, enable_rls

revision = "0002_enable_rls"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

# Tables carrying a company_id column.
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
]

# Tables that also carry the soft-delete columns (hide deleted by default).
SOFT_DELETE_TABLES = [
    "users",
    "projects",
    "cost_entries",
    "client_invoices",
    "subcontractors",
    "equipment_log",
    "budget_line_items",
]

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    # companies: isolate by primary key id
    enable_rls("companies")
    op.execute("ALTER TABLE companies FORCE ROW LEVEL SECURITY;")
    create_policy("companies_company_isolation", "companies",
                  f"FOR ALL USING (id = {CURRENT_COMPANY})")

    for table in COMPANY_SCOPED_TABLES:
        enable_rls(table)
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        create_policy(f"{table}_company_isolation", table,
                      f"FOR ALL USING (company_id = {CURRENT_COMPANY})")

    for table in SOFT_DELETE_TABLES:
        create_policy(f"{table}_hide_deleted", table,
                      "FOR SELECT USING (is_deleted = false)")

    # audit_log is append-only: no UPDATE or DELETE permitted via RLS.
    create_policy("audit_log_append_only_no_update", "audit_log", "FOR UPDATE USING (false)")
    create_policy("audit_log_append_only_no_delete", "audit_log", "FOR DELETE USING (false)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS companies_company_isolation ON companies;")
    op.execute("ALTER TABLE companies DISABLE ROW LEVEL SECURITY;")
    for table in COMPANY_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_company_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    for table in SOFT_DELETE_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_hide_deleted ON {table};")
    op.execute("DROP POLICY IF EXISTS audit_log_append_only_no_update ON audit_log;")
    op.execute("DROP POLICY IF EXISTS audit_log_append_only_no_delete ON audit_log;")
