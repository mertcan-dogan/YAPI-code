"""CR-040 hotfix capture: alembic_version SELECT policy for the app role

Revision ID: 0041_alembic_version_app_read
Revises: 0040_rls_guc_isolation
Create Date: 2026-06-24

Records a hotfix already applied to prod during the CR-040 env-flip: a SELECT
policy on ``public.alembic_version`` for the NOBYPASSRLS app role ``yapi_app``, so
the boot migration-head check and ``/health``'s alembic_version read work under
that role. Capturing it here keeps Alembic history in sync with the live DB.

Belt-and-suspenders: this release also routes those two reads through the
escalated (service_role) session (app/main.py), so the policy is no longer the
only thing keeping them working — but recording the policy keeps history honest.

Additive, no behaviour change. GUARDED so it is a clean no-op where the role does
not exist yet (fresh DBs, pre-cutover) — ``CREATE POLICY ... TO yapi_app`` errors
if the role is absent. Migrations only run on Postgres (run_migrations skips
non-Postgres URLs), so the Postgres-only DO block never reaches SQLite tests.
"""
from alembic import op

revision = "0041_alembic_version_app_read"
down_revision = "0040_rls_guc_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'yapi_app')
               AND EXISTS (
                   SELECT 1 FROM information_schema.tables
                   WHERE table_schema = 'public' AND table_name = 'alembic_version'
               ) THEN
                DROP POLICY IF EXISTS alembic_version_app_read ON public.alembic_version;
                CREATE POLICY alembic_version_app_read ON public.alembic_version
                    FOR SELECT TO yapi_app USING (true);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # alembic_version always exists while a migration runs; the policy may not, so
    # IF EXISTS keeps this clean. Independent of the yapi_app role's presence.
    op.execute(
        "DROP POLICY IF EXISTS alembic_version_app_read ON public.alembic_version;"
    )
