"""Projects router: CRUD, project dashboard, budget, company dashboard (Section 2.5, 4.1-4.3)."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Request
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations.money import D, money, pct, safe_div
from app.constants import COST_CATEGORIES, COST_CATEGORY_KEYS
from app.db import get_db
from app.deps import CurrentUser, DirectorUser
from app.models.budget_line_item import BudgetLineItem
from app.models.project import Project
from app.responses import APIError, success
from app.schemas.budget import BudgetForecastUpdate, BudgetLineOut
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import financials as fin_service
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot

router = APIRouter(tags=["projects"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _list_visible_projects(db: Session, user: CurrentUser, only_active: bool = False):
    stmt = select(Project).where(
        Project.company_id == user.company_id, Project.is_deleted.is_(False)
    )
    if only_active:
        stmt = stmt.where(Project.status == "active")
    projects = db.execute(stmt).scalars().all()
    # PM / Site managers see only their own projects (Section 3.2).
    from app.constants import ROLE_PROJECT_MANAGER, ROLE_SITE_MANAGER

    if user.role in (ROLE_PROJECT_MANAGER, ROLE_SITE_MANAGER):
        projects = [p for p in projects if not p.project_manager_id or p.project_manager_id == user.id]
    return projects


@router.get("/projects")
def list_projects(user: CurrentUser, db: Session = Depends(get_db)):
    projects = _list_visible_projects(db, user)
    out = []
    for p in projects:
        f = fin_service.project_financials(db, p)
        row = ProjectOut.model_validate(p).model_dump(mode="json")
        row["financials"] = _summary(f)
        out.append(row)
    return success(out, meta={"total": len(out)})


def _summary(f: dict) -> dict:
    """Compact KPI summary for list/dashboard rows."""
    keys = [
        "contract_value_try", "revised_budget_try", "total_committed_try",
        "total_actual_try", "total_actual_with_vat_try", "remaining_budget_try",
        "forecast_final_cost_try", "current_profit_try", "margin_pct",
        "total_invoiced_try", "total_collected_try", "total_outstanding_try",
        "total_retention_try", "net_cash_position_try", "overdue_count",
        "max_overdue_days", "time_completion_pct", "completion_pct",
        "rag_status", "rag_label_tr", "rag_reason_tr",
    ]
    return _jsonify({k: f[k] for k in keys})


@router.post("/projects")
def create_project(
    payload: ProjectCreate,
    request: Request,
    user: DirectorUser,
    db: Session = Depends(get_db),
):
    project = Project(
        company_id=user.company_id,
        **payload.model_dump(),
    )
    db.add(project)
    db.flush()
    # Seed budget line items for all categories (Section 11 step 4, optional later edit).
    for cat in COST_CATEGORY_KEYS:
        db.add(BudgetLineItem(project_id=project.id, company_id=user.company_id, cost_category=cat))
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="projects",
        record_id=project.id, action="INSERT", new_values=snapshot(project),
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(project)
    return success(ProjectOut.model_validate(project).model_dump(mode="json"))


@router.get("/projects/{project_id}")
def get_project(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    return success(ProjectOut.model_validate(project).model_dump(mode="json"))


@router.put("/projects/{project_id}")
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    # Only directors may edit project settings; PMs may update completion_pct only.
    from app.constants import ROLE_DIRECTOR

    changes = payload.model_dump(exclude_unset=True)
    if user.role != ROLE_DIRECTOR:
        allowed = {"completion_pct"}
        if set(changes) - allowed:
            raise APIError(403, "FORBIDDEN", "Proje ayarlarını yalnızca yönetici düzenleyebilir")

    old = snapshot(project)
    for k, v in changes.items():
        setattr(project, k, v)
    project.last_modified_by = user.id if hasattr(project, "last_modified_by") else None
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="projects",
        record_id=project.id, action="UPDATE", old_values=old, new_values=snapshot(project),
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(project)
    return success(ProjectOut.model_validate(project).model_dump(mode="json"))


@router.get("/projects/{project_id}/dashboard")
def project_dashboard(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    f = fin_service.project_financials(db, project)
    cashflow = fin_service.project_cashflow(db, project)
    return success(
        {
            "project": ProjectOut.model_validate(project).model_dump(mode="json"),
            "financials": _jsonify(f),
            "cashflow": _jsonify_list(cashflow),
        }
    )


# --- Budget (Section 4.3) ---
@router.get("/projects/{project_id}/budget")
def get_budget(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    # CR-002-A: include company custom categories so they always appear in the table.
    from app.models.custom_category import CustomCostCategory

    custom = db.execute(
        select(CustomCostCategory).where(
            CustomCostCategory.company_id == user.company_id,
            CustomCostCategory.is_deleted.is_(False),
        )
    ).scalars().all()
    custom_names = [c.name for c in custom]
    f = fin_service.project_financials(db, project, extra_category_keys=custom_names)

    # Totals across the category rows (CR-002-A totals row).
    from app.calculations.money import D, money

    cats = f["categories"]
    rows = []
    tot_revised = tot_committed = tot_invoiced = tot_paid = D(0)
    for c in cats:
        row = _jsonify(c)
        row["label_tr"] = COST_CATEGORIES.get(c["cost_category"], c["cost_category"])
        rows.append(row)
        tot_revised += c["revised_budget_try"]
        tot_committed += c["committed_try"]
        tot_invoiced += c["invoiced_try"]
        tot_paid += c["paid_try"]
    return success(
        {
            "categories": rows,
            "totals": {
                "revised_budget_try": str(money(tot_revised)),
                "committed_try": str(money(tot_committed)),
                "invoiced_try": str(money(tot_invoiced)),
                "paid_try": str(money(tot_paid)),
                "remaining_try": str(money(tot_revised - tot_committed)),
                "forecast_final_cost_try": str(f["forecast_final_cost_try"]),
            },
        }
    )


@router.put("/projects/{project_id}/budget/{category}")
def update_budget(
    project_id: uuid.UUID,
    category: str,
    payload: BudgetForecastUpdate,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    if category not in COST_CATEGORY_KEYS:
        # CR-002-A: allow editing the budget of a company custom category too.
        from app.models.custom_category import CustomCostCategory

        norm = " ".join(category.strip().lower().split())
        is_custom = db.execute(
            select(CustomCostCategory).where(
                CustomCostCategory.company_id == user.company_id,
                CustomCostCategory.name_normalized == norm,
                CustomCostCategory.is_deleted.is_(False),
            )
        ).scalar_one_or_none()
        if is_custom is None:
            raise APIError(422, "VALIDATION_ERROR", "Geçersiz kategori", field="category")
    line = db.execute(
        select(BudgetLineItem).where(
            BudgetLineItem.project_id == project.id,
            BudgetLineItem.cost_category == category,
            BudgetLineItem.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if line is None:
        line = BudgetLineItem(project_id=project.id, company_id=user.company_id, cost_category=category)
        db.add(line)
        db.flush()
    old = snapshot(line)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(line, k, v)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="budget_line_items",
        record_id=line.id, action="UPDATE", old_values=old, new_values=snapshot(line),
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(line)
    return success(BudgetLineOut.model_validate(line).model_dump(mode="json"))


# --- Company dashboard (Section 4.1) ---
@router.get("/dashboard")
def company_dashboard(user: CurrentUser, db: Session = Depends(get_db)):
    projects = _list_visible_projects(db, user, only_active=True)
    rows = []
    total_contract = D(0)
    weighted_margin_num = D(0)
    overdue_total = 0
    combined_cashflow: dict[str, dict] = {}

    for p in projects:
        f = fin_service.project_financials(db, p)
        total_contract += f["contract_value_try"]
        weighted_margin_num += f["current_profit_try"]
        overdue_total += f["overdue_count"]
        rows.append(
            {
                "id": str(p.id),
                "name": p.name,
                "client_name": p.client_name,
                "contract_value_try": str(f["contract_value_try"]),
                "spent_pct": str(pct(safe_div(f["total_actual_try"], f["revised_budget_try"]) * 100)),
                "completion_pct": str(f["completion_pct"]),
                "margin_pct": str(f["margin_pct"]),
                "net_cash_position_try": str(f["net_cash_position_try"]),
                "rag_status": f["rag_status"],
                "rag_label_tr": f["rag_label_tr"],
                "planned_end_date": p.planned_end_date.isoformat(),
                "overdue": p.planned_end_date < date.today(),
            }
        )
        for cf in fin_service.project_cashflow(db, p):
            agg = combined_cashflow.setdefault(
                cf["month"], {"month": cf["month"], "out": D(0), "in": D(0)}
            )
            out_v = cf["actual_out_try"] if (cf["is_past"] or cf["is_current"]) else cf["planned_out_try"]
            in_v = cf["actual_in_try"] if (cf["is_past"] or cf["is_current"]) else cf["planned_in_try"]
            agg["out"] += out_v
            agg["in"] += in_v

    weighted_margin = pct(safe_div(weighted_margin_num, total_contract) * 100)

    # Last 6 months combined cash flow for the chart.
    cashflow_chart = []
    cumulative = D(0)
    for month in sorted(combined_cashflow):
        c = combined_cashflow[month]
        net = c["in"] - c["out"]
        cumulative += net
        cashflow_chart.append(
            {"month": month, "out": str(money(c["out"])), "in": str(money(c["in"])),
             "net_cumulative": str(money(cumulative))}
        )
    cashflow_chart = cashflow_chart[-6:]

    return success(
        {
            "kpis": {
                "active_project_count": len(projects),
                "total_contract_value_try": str(money(total_contract)),
                "weighted_avg_margin_pct": str(weighted_margin),
                "overdue_payment_count": overdue_total,
            },
            "projects": rows,
            "cashflow_chart": cashflow_chart,
        }
    )


# --- jsonify helpers (Decimal/date -> str) ---
def _jsonify(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if hasattr(v, "quantize"):
            out[k] = str(v)
        elif isinstance(v, date):
            out[k] = v.isoformat()
        elif isinstance(v, list):
            out[k] = _jsonify_list(v)
        else:
            out[k] = v
    return out


def _jsonify_list(items: list) -> list:
    return [_jsonify(i) if isinstance(i, dict) else i for i in items]
