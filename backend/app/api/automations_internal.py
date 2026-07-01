"""CR-012 §7 — the one new piece of scheduler infra.

``POST /internal/automations/run-due`` is the authenticated internal endpoint an
external cron (Railway native Cron, fallback cron-job.org) hits on a schedule. It
has **no user auth** — it is gated solely by the ``X-Internal-Secret`` header
matching ``settings.internal_cron_secret`` (a Railway env var, never committed).
A blank secret or a mismatch returns 401 and runs nothing, so the endpoint can
never be triggered accidentally or by an unauthorised caller.

It is idempotent (driven by ``next_run_at`` + the per-period guard in
``services/automations``), so it is safe to call as often as hourly.
"""
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_admin_db
from app.responses import APIError, success
from app.services import automations as automations_service

router = APIRouter(tags=["automations-internal"])


@router.post("/internal/automations/run-due")
def run_due_automations(
    x_internal_secret: Annotated[str | None, Header()] = None,
    # CR-040: cron has no user/company → must run on the escalated (RLS-bypassing)
    # session, else under the app role it would see zero rows and process nothing.
    db: Session = Depends(get_admin_db),
):
    secret = settings.internal_cron_secret
    # No configured secret => endpoint is closed. Constant-time compare otherwise.
    if not secret or not x_internal_secret or not hmac.compare_digest(x_internal_secret, secret):
        raise APIError(401, "UNAUTHENTICATED", "Yetkisiz")
    result = automations_service.run_due_automations(db)
    return success(result)
