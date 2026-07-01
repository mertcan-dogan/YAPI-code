"""CR-041: invites table for teammate invitation/acceptance + its RLS policy

Revision ID: 0042_invites
Revises: 0041_alembic_version_app_read
Create Date: 2026-06-24

Additive only — one new company-scoped table, ``invites``, backing teammate
invitation/acceptance (audit #1: directors could not add teammates; the link
dead-ended and created a brand-new company). A director creates a tokenized,
7-day invite; the invitee accepts via /accept-invite?token=… which creates their
public.users row attached to the INVITING company. Existing companies have no
rows → zero behaviour change until a director sends an invite.

RLS (post-0040 model)
---------------------
Isolation policy uses the per-request GUC ``app.current_company`` with WITH CHECK,
exactly like the 0040 tables — so a director can only list/create/revoke invites
in their OWN company on the request (NOBYPASSRLS ``yapi_app``) session. No
``*_hide_deleted`` policy is added (0040 deliberately dropped those; soft-delete
hiding is done in app code). NO FORCE is left off to match every other table.

DELIBERATE: NO public ``TO yapi_app`` read policy on ``invites``. The token
lookup (GET /auth/invite/{token}) and acceptance (POST /auth/invite/{token}/accept)
happen BEFORE the visitor has any company context, so they run on the ESCALATED
(service_role) session, which is RLS-exempt. Adding a yapi_app SELECT policy here
would create a token-guessing read surface for no benefit — so we don't. A future
dev must not "fix" this by adding one. (Contrast 0041's alembic_version, where the
app role genuinely needs the read.)

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

revision = "0042_invites"
down_revision = "0041_alembic_version_app_read"
branch_labels = None
depends_on = None

# Per-request GUC — identical to 0040. NULLIF(...,'') collapses an unset/empty
# value to NULL (fail-closed: no company context ⇒ zero rows).
GUC = "NULLIF(current_setting('app.current_company', true), '')::uuid"


def upgrade() -> None:
    create_table(
        "invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("accepted_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token", name="uq_invites_token"),
    )
    create_index("ix_invites_company", "invites", ["company_id"])

    # Tenant isolation on the request (yapi_app) session. The accept/lookup flow
    # uses the escalated session and is intentionally NOT covered by a read policy.
    enable_rls("invites")
    op.execute("ALTER TABLE invites NO FORCE ROW LEVEL SECURITY;")
    create_policy(
        "invites_company_isolation",
        "invites",
        f"FOR ALL USING (company_id = {GUC}) WITH CHECK (company_id = {GUC})",
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS invites_company_isolation ON invites;")
    op.drop_index("ix_invites_company", table_name="invites")
    op.drop_table("invites")
