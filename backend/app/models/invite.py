"""invites table (CR-041): pending teammate invitations to a company.

A director creates an invite (status=pending, an opaque single-use token, 7-day
expiry). The invitee accepts via {FRONTEND_URL}/accept-invite?token=…, which
creates their public.users row attached to THIS company (not a brand-new one)
with the invited role. The accept/lookup flow runs on the escalated
(RLS-bypassing) session because the visitor has no company context yet.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import INVITE_PENDING
from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID


class Invite(TimestampSoftDeleteMixin, Base):
    __tablename__ = "invites"

    # No index=True here: the company_id index (ix_invites_company) is created by
    # migration 0042, matching the repo convention (see 0037_automations). Putting
    # it on the model too would create a duplicate index on fresh (create_all) DBs.
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    # Opaque single-use token (secrets.token_urlsafe). Globally unique so the
    # public accept link can resolve it without a company context (the unique
    # constraint already backs token lookups with an index).
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=INVITE_PENDING, server_default=INVITE_PENDING
    )
    invited_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
