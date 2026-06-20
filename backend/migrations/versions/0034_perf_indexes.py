"""perf: project_id indexes on the hot cost/invoice tables

Revision ID: 0034_perf_indexes
Revises: 0033_agent_actions
Create Date: 2026-06-20

The project list / company dashboard / single-project dashboard load a project's
cost_entries and client_invoices filtered by ``project_id`` (and ``project_id IN
(...)`` for the batch path). Postgres does NOT auto-index foreign keys, so these
were sequential scans — the dominant cost of the slow dashboards. Add composite
``(project_id, is_deleted)`` indexes matching the WHERE clause. budget_line_items
already has a unique index on (project_id, cost_category) that covers project_id
lookups, so it needs nothing.

Additive + idempotent (create_index skips if present). revision id <= 32 chars.
"""
from alembic import op

from migrations.idempotent import create_index

revision = "0034_perf_indexes"
down_revision = "0033_agent_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_index("ix_cost_entries_project", "cost_entries", ["project_id", "is_deleted"])
    create_index("ix_client_invoices_project", "client_invoices", ["project_id", "is_deleted"])


def downgrade() -> None:
    op.drop_index("ix_client_invoices_project", table_name="client_invoices")
    op.drop_index("ix_cost_entries_project", table_name="cost_entries")
