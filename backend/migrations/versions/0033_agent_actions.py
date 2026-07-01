"""CR-011-C: agent write-with-approval — proposed_by_agent flag on approval_requests

Revision ID: 0033_agent_actions
Revises: 0032_assurance_alert_fields
Create Date: 2026-06-19

Additive only — one nullable boolean column on the existing ``approval_requests``
table so an approval request can be tagged as agent-proposed (CR-011-C). Existing
requests keep the default ``false`` → zero behavior change. The new agent kinds
(agent_reminder | agent_flag_invoice | agent_task) are plain ``kind`` string
values and need no schema change (kind is already VARCHAR(40)). Reuses the
table's existing RLS (no policy change).

NOTE: revision id <= 32 chars (alembic_version.version_num is VARCHAR(32) — the
CR-007 0021 trap). "0033_agent_actions" is 18 chars.
"""
import sqlalchemy as sa
from alembic import op

from migrations.idempotent import add_column

revision = "0033_agent_actions"
down_revision = "0032_assurance_alert_fields"
branch_labels = None
depends_on = None

TABLE = "approval_requests"


def upgrade() -> None:
    add_column(
        TABLE,
        sa.Column("proposed_by_agent", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column(TABLE, "proposed_by_agent")
