"""CR-033 — Report Studio persistence schemas.

A saved Report is a stored CR-032 ``spec`` plus ownership/visibility metadata. The
``visibility`` ``Literal`` is defense-in-depth: anything other than
"private"/"company" (e.g. the deferred "team", or garbage) is rejected with 422 at
the Pydantic layer, never reaching the DB. ``is_owner`` on ``ReportOut`` is filled
by the endpoint (``owner_id == user.id``); it is not a column.
"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ReportCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    spec: dict
    visibility: Literal["private", "company"] = "private"
    labels: list[str] | None = None


class ReportUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    spec: dict | None = None
    visibility: Literal["private", "company"] | None = None
    labels: list[str] | None = None


class ReportOut(ORMModel):
    id: uuid.UUID
    title: str
    spec: dict
    visibility: str
    labels: list[str] | None = None
    owner_id: uuid.UUID
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    is_owner: bool


class ReportListItem(BaseModel):
    """Lightweight row for the list view — no full spec, just the picker preview."""

    id: uuid.UUID
    title: str
    owner_id: uuid.UUID
    visibility: str
    updated_at: datetime
    labels: list[str] | None = None
    viz: str = "table"
