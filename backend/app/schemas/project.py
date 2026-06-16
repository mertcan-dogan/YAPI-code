"""Project schemas (Section 11 wizard, Section 4.2)."""
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator, model_validator

from app.constants import PROJECT_STATUSES, PROJECT_TYPES, UNIT_TYPE_KEYS
from app.schemas.common import ERR_CONTRACT, ERR_RETENTION, ORMModel

ERR_UNIT_TYPE = "Geçersiz daire tipi"
ERR_UNIT_CUSTOM = "Diğer için açıklama girin"
ERR_UNIT_COUNT = "Adet en az 1 olmalıdır"
ERR_UNIT_M2 = "m² 0'dan büyük olmalıdır"


class UnitScheduleIn(BaseModel):
    """A daire dağılımı row on project create/update (CR-016-A).

    ``id`` targets an existing row on update (CR-016-B upsert); omit it for new
    rows. An id that doesn't belong to the caller's company is treated as new.
    """

    id: uuid.UUID | None = None
    unit_type: str
    custom_label: str | None = None
    count: int = 1
    gross_m2_each: Decimal
    net_m2_each: Decimal | None = None
    sale_price_try: Decimal | None = None
    notes: str | None = None

    @field_validator("unit_type")
    @classmethod
    def _unit_type(cls, v: str) -> str:
        if v not in UNIT_TYPE_KEYS:
            raise ValueError(ERR_UNIT_TYPE)
        return v

    @field_validator("count")
    @classmethod
    def _count(cls, v: int) -> int:
        if v is None or v < 1:
            raise ValueError(ERR_UNIT_COUNT)
        return v

    @field_validator("gross_m2_each")
    @classmethod
    def _gross(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError(ERR_UNIT_M2)
        return v

    @field_validator("net_m2_each", "sale_price_try")
    @classmethod
    def _optional_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError(ERR_UNIT_M2)
        return v

    @model_validator(mode="after")
    def _custom_label(self):
        if self.unit_type == "other" and not (self.custom_label or "").strip():
            raise ValueError(ERR_UNIT_CUSTOM)
        return self


class UnitScheduleOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    company_id: uuid.UUID
    unit_type: str
    custom_label: str | None
    count: int
    gross_m2_each: Decimal
    net_m2_each: Decimal | None
    sale_price_try: Decimal | None
    notes: str | None


class ProjectCreate(BaseModel):
    name: str
    project_code: str
    project_type: str
    revenue_model: str = "hakedis"
    custom_project_type: str | None = None
    contractor_share_pct: Decimal | None = None
    unit_count: int | None = None
    client_name: str
    client_contact: str | None = None
    contract_number: str | None = None
    location: str | None = None
    description: str | None = None

    contract_value_try: Decimal
    contract_value_eur: Decimal | None = None
    contract_value_usd: Decimal | None = None
    eur_try_rate: Decimal = Decimal("1.0")
    usd_try_rate: Decimal = Decimal("1.0")

    start_date: date
    planned_end_date: date

    retention_pct: Decimal = Decimal("10.00")
    contingency_pct: Decimal = Decimal("5.00")
    original_budget_try: Decimal
    target_margin_pct: Decimal | None = None
    project_manager_id: uuid.UUID | None = None

    # CR-016-A: residential details (construction area + daire dağılımı). All
    # optional — non-residential projects simply omit them. Persistence wired in CR-016-B.
    construction_gross_m2: Decimal | None = None
    construction_net_m2: Decimal | None = None
    units: list[UnitScheduleIn] = []

    # CR-015-A: financing overrides (NULL = inherit the company default).
    financing_enabled_override: bool | None = None
    financing_annual_rate_pct_override: Decimal | None = None

    @field_validator("project_type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in PROJECT_TYPES:
            raise ValueError("Geçersiz proje türü")
        return v

    @field_validator("revenue_model")
    @classmethod
    def _revenue_model(cls, v: str) -> str:
        allowed = {"hakedis", "kat_karsiligi", "yap_sat", "hasilat_paylasimi", "maliyet_kar"}
        if v not in allowed:
            raise ValueError("Geçersiz gelir modeli")
        return v

    @field_validator("contract_value_try")
    @classmethod
    def _contract(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError(ERR_CONTRACT)
        return v

    @field_validator("retention_pct")
    @classmethod
    def _retention(cls, v: Decimal) -> Decimal:
        if v is None or v < 0 or v > 50:
            raise ValueError(ERR_RETENTION)
        return v

    @model_validator(mode="after")
    def _dates(self):
        if self.planned_end_date < self.start_date:
            raise ValueError("Planlanan bitiş tarihi başlangıç tarihinden önce olamaz")
        # CR-001-A: a custom type is required when "Diğer" is selected.
        if self.project_type == "other" and not (self.custom_project_type or "").strip():
            raise ValueError("Lütfen proje türünü belirtin")
        if self.custom_project_type and len(self.custom_project_type) > 100:
            raise ValueError("Proje türü en fazla 100 karakter olabilir")
        return self


class ProjectUpdate(BaseModel):
    name: str | None = None
    project_type: str | None = None
    custom_project_type: str | None = None
    client_name: str | None = None
    client_contact: str | None = None
    contract_number: str | None = None
    location: str | None = None
    description: str | None = None
    contract_value_try: Decimal | None = None
    contract_value_eur: Decimal | None = None
    eur_try_rate: Decimal | None = None
    planned_end_date: date | None = None
    actual_end_date: date | None = None
    status: str | None = None
    retention_pct: Decimal | None = None
    contingency_pct: Decimal | None = None
    original_budget_try: Decimal | None = None
    approved_variations_try: Decimal | None = None
    target_margin_pct: Decimal | None = None
    completion_pct: Decimal | None = None
    project_manager_id: uuid.UUID | None = None

    # CR-016-A: residential details editable after creation (persistence in CR-016-B).
    construction_gross_m2: Decimal | None = None
    construction_net_m2: Decimal | None = None
    units: list[UnitScheduleIn] | None = None

    # CR-015-A: financing overrides (NULL = inherit the company default).
    financing_enabled_override: bool | None = None
    financing_annual_rate_pct_override: Decimal | None = None

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is not None and v not in PROJECT_STATUSES:
            raise ValueError("Geçersiz proje durumu")
        return v

    @field_validator("contract_value_try")
    @classmethod
    def _contract(cls, v):
        if v is not None and v <= 0:
            raise ValueError(ERR_CONTRACT)
        return v

    @field_validator("retention_pct")
    @classmethod
    def _retention(cls, v):
        if v is not None and (v < 0 or v > 50):
            raise ValueError(ERR_RETENTION)
        return v


class ProjectOut(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    project_code: str
    project_type: str
    custom_project_type: str | None
    client_name: str
    client_contact: str | None
    contract_number: str | None
    location: str | None
    description: str | None
    contract_value_try: Decimal
    contract_value_eur: Decimal | None
    contract_value_usd: Decimal | None
    eur_try_rate: Decimal
    usd_try_rate: Decimal
    start_date: date
    planned_end_date: date
    actual_end_date: date | None
    status: str
    retention_pct: Decimal
    contingency_pct: Decimal
    original_budget_try: Decimal
    approved_variations_try: Decimal
    target_margin_pct: Decimal | None
    completion_pct: Decimal
    project_manager_id: uuid.UUID | None
    # CR-016-A: residential details (empty units for non-residential projects).
    construction_gross_m2: Decimal | None = None
    construction_net_m2: Decimal | None = None
    units: list[UnitScheduleOut] = []
    # CR-015-A: financing overrides (NULL = inherit company default).
    financing_enabled_override: bool | None = None
    financing_annual_rate_pct_override: Decimal | None = None
