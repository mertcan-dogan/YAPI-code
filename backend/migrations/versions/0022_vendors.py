"""CR-008-E: vendors + vendor_aliases tables; nullable vendor_id FKs

Revision ID: 0022_vendors
Revises: 0021_pg_trgm_ai_query_log
Create Date: 2026-06-15

Real vendor entity so cross-project spend matching can be exact (vendor_id +
aliases) instead of fragile pg_trgm name normalisation. Additive only — existing
cost_entries.supplier_name / subcontractors.name stay; a NULLABLE vendor_id FK is
added alongside, so existing rows are untouched (vendor_id NULL) until linked by
the CR-008-F backfill (§0.2).

NOTE: revision id kept short (<= 32 chars) — alembic_version.version_num is
VARCHAR(32) (the CR-007 0021 trap).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotent import add_column, create_index, create_policy, create_table, enable_rls

revision = "0022_vendors"
down_revision = "0021_pg_trgm_ai_query_log"
branch_labels = None
depends_on = None

CURRENT_COMPANY = "(SELECT company_id FROM users WHERE id = auth.uid())"


def upgrade() -> None:
    # --- vendors ---
    create_table(
        "vendors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("tax_id", sa.String(50), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(30), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("company_id", "canonical_name", name="uq_vendors_company_canonical"),
    )
    create_index("ix_vendors_company", "vendors", ["company_id"])

    # --- vendor_aliases ---
    create_table(
        "vendor_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("alias_name", sa.String(255), nullable=False),
        sa.Column("alias_normalised", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index("ix_vendor_aliases_lookup", "vendor_aliases", ["company_id", "alias_normalised"])

    # --- additive nullable FKs on existing tables (do NOT touch supplier_name/name) ---
    add_column("cost_entries", sa.Column(
        "vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id"), nullable=True))
    add_column("subcontractors", sa.Column(
        "vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id"), nullable=True))
    create_index("ix_cost_entries_vendor", "cost_entries", ["vendor_id"])
    create_index("ix_subcontractors_vendor", "subcontractors", ["vendor_id"])

    # --- RLS parity (defence in depth) ---
    for table in ("vendors", "vendor_aliases"):
        enable_rls(table)
        create_policy(f"{table}_company_isolation", table,
                      f"FOR ALL USING (company_id = {CURRENT_COMPANY})")
        create_policy(f"{table}_hide_deleted", table,
                      "FOR SELECT USING (is_deleted = false)")


def downgrade() -> None:
    for table in ("vendors", "vendor_aliases"):
        op.execute(f"DROP POLICY IF EXISTS {table}_hide_deleted ON {table};")
        op.execute(f"DROP POLICY IF EXISTS {table}_company_isolation ON {table};")
    op.drop_index("ix_subcontractors_vendor", table_name="subcontractors")
    op.drop_index("ix_cost_entries_vendor", table_name="cost_entries")
    op.drop_column("subcontractors", "vendor_id")
    op.drop_column("cost_entries", "vendor_id")
    op.drop_index("ix_vendor_aliases_lookup", table_name="vendor_aliases")
    op.drop_table("vendor_aliases")
    op.drop_index("ix_vendors_company", table_name="vendors")
    op.drop_table("vendors")
