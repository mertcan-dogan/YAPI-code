"""CR-032 §5 — Report Studio read-only endpoints.

Two endpoints, ``CurrentUser``-gated and company-scoped. ``company_id`` always
comes from the authenticated user, NEVER from the request body. No persistence,
no new model, no migration (CR-033 adds ``/studio/reports`` etc.).
"""
from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser
from app.responses import success
from app.services.studio.catalog import get_catalog_public
from app.services.studio.engine import run_spec

router = APIRouter(tags=["studio"])


@router.get("/studio/catalog")
def studio_catalog(user: CurrentUser):
    """The dimension/metric catalog (id/label/type/group/description/status only)
    that drives the CR-033 picker. Cacheable; no per-company data."""
    return success(get_catalog_public())


@router.post("/studio/run")
def studio_run(user: CurrentUser, spec: dict = Body(...), db: Session = Depends(get_db)):
    """Run a Spec (§2) and return the result shape (§2). A malformed spec raises
    ``APIError(422)`` (handled by the global error middleware). The engine is
    read-only and scoped to ``user.company_id``."""
    return success(run_spec(db, user.company_id, spec))
