"""User & company schemas (Section 3, 11)."""
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

from app.constants import ROLES
from app.schemas.common import ORMModel


class UserInvite(BaseModel):
    email: EmailStr
    full_name: str
    role: str

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError("Geçersiz kullanıcı rolü")
        return v


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    phone: str | None = None
    preferred_language: str | None = None
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v is not None and v not in ROLES:
            raise ValueError("Geçersiz kullanıcı rolü")
        return v


class UserOut(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    full_name: str
    email: str
    role: str
    phone: str | None
    preferred_language: str
    is_active: bool
    last_login_at: datetime | None


class CompanyOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    tax_number: str | None
    address: str | None
    phone: str | None
    email: str | None
    default_currency: str
    retention_default_pct: float
    vat_rate_default: float
    logo_url: str | None
    subscription_status: str
    fiscal_year_start_month: int


class CompanyUpdate(BaseModel):
    name: str | None = None
    tax_number: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    default_currency: str | None = None
    retention_default_pct: float | None = None
    vat_rate_default: float | None = None
    logo_url: str | None = None
    fiscal_year_start_month: int | None = None
