"""Cash flow router (Section 2.5, 4.6)."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser
from app.responses import APIError, success
from app.services.access import get_company_project
from app.services.financials import (
    cash_need_windows,
    cashflow_month_detail,
    project_cashflow_window,
    project_usd_totals,
)

router = APIRouter(tags=["cashflow"])


def _jsonify(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({k: (str(v) if hasattr(v, "quantize") else v) for k, v in r.items()})
    return out


def _valid_month(value: str) -> bool:
    try:
        y, m = value.split("-")
        return len(y) == 4 and 1 <= int(m) <= 12 and int(y) >= 1
    except (ValueError, AttributeError):
        return False


@router.get("/projects/{project_id}/cashflow")
def get_cashflow(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: Session = Depends(get_db),
    from_month: str | None = None,
    to_month: str | None = None,
):
    """Monthly cashflow. With from_month/to_month (YYYY-MM) the window is that
    range and the cumulative is seeded with the opening balance carried in from
    before it; omitting both keeps the fixed rolling window (no regression)."""
    project = get_company_project(db, project_id, user)

    # A range needs both ends, each well-formed, with from <= to (Turkish 422).
    if (from_month is None) != (to_month is None):
        raise APIError(422, "INVALID_RANGE", "Hem başlangıç hem bitiş ayı (YYYY-MM) gereklidir")
    if from_month is not None:
        if not _valid_month(from_month) or not _valid_month(to_month):
            raise APIError(422, "INVALID_MONTH", "Geçersiz ay formatı (YYYY-MM bekleniyor)")
        if from_month > to_month:
            raise APIError(422, "INVALID_RANGE", "Başlangıç ayı bitiş ayından sonra olamaz")

    result = project_cashflow_window(db, project, from_month=from_month, to_month=to_month)
    # CR-014-C: USD totals (SUM of per-row amount_usd snapshots) alongside the
    # TRY monthly rows, with a missing-snapshot count. TRY rows unchanged.
    return success(
        _jsonify(result["rows"]),
        meta={
            "usd": project_usd_totals(db, project),
            # Carried-in cumulative position so the UI can show where the period starts.
            "opening_balance_try": str(result["opening_balance_try"]),
            "from_month": from_month,
            "to_month": to_month,
        },
    )


@router.get("/projects/{project_id}/cashflow/risk")
def get_cashflow_risk(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """CR-004-M: 30/60/90-day net cash-need cards."""
    project = get_company_project(db, project_id, user)
    return success(cash_need_windows(db, project))


@router.get("/projects/{project_id}/cashflow/detail")
def get_cashflow_detail(
    project_id: uuid.UUID, user: CurrentUser, month: str, db: Session = Depends(get_db)
):
    """CR-005-D: month drill-down — unpaid costs & uncollected invoices due in month."""
    project = get_company_project(db, project_id, user)
    try:
        year, m = month.split("-")
        int(year), int(m)
    except (ValueError, AttributeError):
        raise APIError(422, "INVALID_MONTH", "Geçersiz ay formatı (YYYY-MM bekleniyor)")
    return success(cashflow_month_detail(db, project, month))
