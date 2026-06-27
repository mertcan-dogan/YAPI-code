"""CR-034 — Report Studio dashboard (pano) persistence schemas.

A saved Dashboard is a canvas of ``widgets`` (KPI/chart/table/text/report) on a
react-grid-layout grid plus dashboard-global ``date_range``/``comparison``/
``filters`` and ownership/visibility metadata. Each ``WidgetSpec`` carries EXACTLY
ONE payload matching its ``type`` — the *envelope* invariant enforced by the
``model_validator`` below (a data widget carries an inline ``spec``, a report
widget a ``report_id``, a text widget ``content``). The INNER CR-032 spec of a
data widget is validated separately by ``catalog.validate_spec`` in the endpoint;
the envelope check here only proves the right slot is filled.

The ``visibility`` ``Literal`` is defense-in-depth — anything other than
"private"/"company" (the deferred "team", or garbage) is rejected with 422 at the
Pydantic layer, never reaching the DB. ``is_owner`` on ``DashboardOut`` is filled
by the endpoint (``owner_id == user.id``); it is not a column.
"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel


class Layout(BaseModel):
    """react-grid-layout cell coordinates for one widget."""

    x: int
    y: int
    w: int
    h: int


class WidgetSpec(BaseModel):
    """One element of a dashboard's ``widgets`` array.

    Envelope invariant (``model_validator`` below): exactly one payload, matching
    ``type`` — kpi/chart/table ⇒ ``spec`` (report_id & content null); report ⇒
    ``report_id`` (spec & content null); text ⇒ ``content`` (spec & report_id
    null).
    """

    id: str
    type: Literal["kpi", "chart", "table", "text", "report"]
    title: str
    layout: Layout
    section: str | None = None
    spec: dict | None = None
    report_id: uuid.UUID | None = None
    content: str | None = None

    @model_validator(mode="after")
    def _check_envelope(self) -> "WidgetSpec":
        if self.type in ("kpi", "chart", "table"):
            if self.spec is None:
                raise ValueError("Bu widget tipi için 'spec' gerekli")
            if self.report_id is not None or self.content is not None:
                raise ValueError("Veri widget'ı yalnızca 'spec' içermeli")
        elif self.type == "report":
            if self.report_id is None:
                raise ValueError("Rapor widget'ı için 'report_id' gerekli")
            if self.spec is not None or self.content is not None:
                raise ValueError("Rapor widget'ı yalnızca 'report_id' içermeli")
        elif self.type == "text":
            if self.content is None:
                raise ValueError("Metin widget'ı için 'content' gerekli")
            if self.spec is not None or self.report_id is not None:
                raise ValueError("Metin widget'ı yalnızca 'content' içermeli")
        return self


class DashboardCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    widgets: list[WidgetSpec] = []
    date_range: dict | None = None
    comparison: dict | None = None
    filters: list[dict] | None = None
    visibility: Literal["private", "company"] = "private"
    labels: list[str] | None = None


class DashboardUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    widgets: list[WidgetSpec] | None = None
    date_range: dict | None = None
    comparison: dict | None = None
    filters: list[dict] | None = None
    visibility: Literal["private", "company"] | None = None
    labels: list[str] | None = None


class DashboardOut(ORMModel):
    id: uuid.UUID
    title: str
    widgets: list[dict]
    date_range: dict | None = None
    comparison: dict | None = None
    filters: list[dict] | None = None
    visibility: str
    labels: list[str] | None = None
    owner_id: uuid.UUID
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    is_owner: bool


class DashboardListItem(BaseModel):
    """Lightweight row for the list view — no full widget array, just a preview."""

    id: uuid.UUID
    title: str
    owner_id: uuid.UUID
    visibility: str
    updated_at: datetime
    labels: list[str] | None = None
    widget_count: int
