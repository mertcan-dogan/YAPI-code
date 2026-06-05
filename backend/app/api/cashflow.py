"""Cash flow router (Section 2.5, 4.6)."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser
from app.responses import success
from app.services.access import get_company_project
from app.services.financials import project_cashflow

router = APIRouter(tags=["cashflow"])


def _jsonify(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({k: (str(v) if hasattr(v, "quantize") else v) for k, v in r.items()})
    return out


@router.get("/projects/{project_id}/cashflow")
def get_cashflow(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    rows = project_cashflow(db, project)
    return success(_jsonify(rows))
