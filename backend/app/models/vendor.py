"""vendors + vendor_aliases tables (CR-008-E).

A real vendor entity so cross-project spend matching can be EXACT (by
``vendor_id`` + aliases) instead of relying on fragile ``pg_trgm`` name
normalisation. Additive: ``cost_entries.supplier_name`` / ``subcontractors.name``
stay; a nullable ``vendor_id`` FK is added alongside (CR-008-E §6.1, §0.2).
"""
import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID


class Vendor(TimestampSoftDeleteMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("company_id", "canonical_name", name="uq_vendors_company_canonical"),
        Index("ix_vendors_company", "company_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)


class VendorAlias(TimestampSoftDeleteMixin, Base):
    """A raw spelling that maps to a canonical vendor. ``alias_normalised`` stores
    the normalised form (CR-007 normalisation) so future imports match exactly."""

    __tablename__ = "vendor_aliases"
    __table_args__ = (
        Index("ix_vendor_aliases_lookup", "company_id", "alias_normalised"),
    )

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    alias_name: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_normalised: Mapped[str] = mapped_column(String(255), nullable=False)
