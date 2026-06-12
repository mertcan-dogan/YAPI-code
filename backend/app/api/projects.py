"""Projects router: CRUD, project dashboard, budget, company dashboard (Section 2.5, 4.1-4.3)."""
import uuid
from datetime import date, timedelta

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
from app.models.kpi_snapshot import KPISnapshot
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
    fac = fin_service.forecast_at_completion(db, project)  # CR-003-F
    bridge = fin_service.margin_bridge(db, project)  # CR-003-G
    return success(
        {
            "project": ProjectOut.model_validate(project).model_dump(mode="json"),
            "financials": _jsonify(f),
            "cashflow": _jsonify_list(cashflow),
            "forecast_at_completion": fac,
            "margin_bridge": bridge,
        }
    )


@router.post("/projects/{project_id}/ai-narrative")
def project_ai_narrative(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """CR-003-F: AI-written 2-3 sentence project summary."""
    from datetime import datetime, timezone

    from app.services import ai as ai_service

    project = get_company_project(db, project_id, user)
    f = fin_service.project_financials(db, project)
    fac = fin_service.forecast_at_completion(db, project)
    summary = {
        "project_name": project.name,
        "margin_pct": str(f["margin_pct"]),
        "forecast_final_margin_pct": fac["forecast_final_margin_pct"],
        "net_cash_position_try": str(f["net_cash_position_try"]),
        "overdue_count": f["overdue_count"],
        "categories_over_100pct": f["categories_over_100pct"],
        "cost_to_complete_try": fac["cost_to_complete_try"],
    }
    narrative = ai_service.project_narrative(summary)
    return success({"narrative": narrative, "generated_at": datetime.now(timezone.utc).isoformat()})


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

    changes = payload.model_dump(exclude_unset=True)
    # CR-004-N: budget changes may require director approval first.
    from app.models.company import Company
    from app.services import approvals as approvals_service

    company = db.get(Company, user.company_id)
    if changes and approvals_service.is_required(company, "budget_change"):
        approvals_service.create_request(
            db, company_id=user.company_id, project_id=project.id,
            kind="budget_change", target_table="budget_line_items", target_id=line.id,
            payload={"category": category, "changes": {k: str(v) for k, v in changes.items()}},
            description=f"Bütçe değişikliği — {COST_CATEGORIES.get(category, category)}",
            requested_by=user.id,
        )
        db.commit()
        out = BudgetLineOut.model_validate(line).model_dump(mode="json")
        out["pending_approval"] = True
        return success(out)

    old = snapshot(line)
    for k, v in changes.items():
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
def _last_n_months(n: int, anchor: date | None = None) -> list[str]:
    """Return the last `n` month keys (YYYY-MM), oldest first, ending at `anchor`."""
    anchor = anchor or date.today()
    y, m = anchor.year, anchor.month
    keys: list[str] = []
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    keys.reverse()
    return keys


def _combined_cashflow_chart(db: Session, project_ids: list, anchor: date | None = None) -> list[dict]:
    """CR-004-B: combined cash flow over the last 6 months across all active projects.

    Expense per month = SUM(cost_entries.total_with_vat_try) WHERE entry_date in month.
    Income per month  = SUM(client_invoices.amount_received_try) WHERE date_received in month.
    Net cumulative is carried forward across the window.
    """
    from app.models.client_invoice import ClientInvoice
    from app.models.cost_entry import CostEntry

    month_keys = _last_n_months(6, anchor)
    buckets = {k: {"out": D(0), "in": D(0)} for k in month_keys}

    if project_ids:
        start_y, start_m = (int(x) for x in month_keys[0].split("-"))
        window_start = date(start_y, start_m, 1)

        cost_rows = db.execute(
            select(CostEntry.entry_date, CostEntry.total_with_vat_try).where(
                CostEntry.project_id.in_(project_ids),
                CostEntry.is_deleted.is_(False),
                CostEntry.pending_approval.is_(False),
                CostEntry.entry_date >= window_start,
            )
        ).all()
        for entry_date, total in cost_rows:
            k = f"{entry_date.year:04d}-{entry_date.month:02d}"
            if k in buckets:
                buckets[k]["out"] += D(total or 0)

        inv_rows = db.execute(
            select(ClientInvoice.date_received, ClientInvoice.amount_received_try).where(
                ClientInvoice.project_id.in_(project_ids),
                ClientInvoice.is_deleted.is_(False),
                ClientInvoice.date_received.is_not(None),
                ClientInvoice.date_received >= window_start,
            )
        ).all()
        for received, amount in inv_rows:
            if received is None:
                continue
            k = f"{received.year:04d}-{received.month:02d}"
            if k in buckets:
                buckets[k]["in"] += D(amount or 0)

    chart = []
    cumulative = D(0)
    for k in month_keys:
        b = buckets[k]
        cumulative += b["in"] - b["out"]
        chart.append(
            {"month": k, "out": str(money(b["out"])), "in": str(money(b["in"])),
             "net_cumulative": str(money(cumulative))}
        )
    return chart


@router.get("/dashboard")
def company_dashboard(user: CurrentUser, db: Session = Depends(get_db)):
    projects = _list_visible_projects(db, user, only_active=True)
    rows = []
    total_contract = D(0)
    weighted_margin_num = D(0)
    overdue_total = 0

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

    weighted_margin = pct(safe_div(weighted_margin_num, total_contract) * 100)

    cashflow_chart = _combined_cashflow_chart(db, [p.id for p in projects])

    kpi_trends = _record_and_build_kpi_trends(
        db,
        company_id=user.company_id,
        active_project_count=len(projects),
        total_contract_value=money(total_contract),
        weighted_avg_margin=weighted_margin,
        overdue_payment_count=overdue_total,
    )

    return success(
        {
            "kpis": {
                "active_project_count": len(projects),
                "total_contract_value_try": str(money(total_contract)),
                "weighted_avg_margin_pct": str(weighted_margin),
                "overdue_payment_count": overdue_total,
            },
            "kpi_trends": kpi_trends,
            "projects": rows,
            "cashflow_chart": cashflow_chart,
        }
    )


def _record_and_build_kpi_trends(db, *, company_id, active_project_count, total_contract_value, weighted_avg_margin, overdue_payment_count):
    """Upsert today's KPI snapshot, then return real trend series + deltas.

    Series/deltas are based purely on recorded daily snapshots — they stay empty
    until at least two distinct days exist, so nothing is ever fabricated.
    """
    today = date.today()
    snap = db.execute(
        select(KPISnapshot).where(
            KPISnapshot.company_id == company_id,
            KPISnapshot.snapshot_date == today,
        )
    ).scalar_one_or_none()
    values = dict(
        active_project_count=active_project_count,
        total_contract_value_try=total_contract_value,
        weighted_avg_margin_pct=weighted_avg_margin,
        overdue_payment_count=overdue_payment_count,
    )
    if snap is None:
        db.add(KPISnapshot(company_id=company_id, snapshot_date=today, **values))
    else:
        for k_, v_ in values.items():
            setattr(snap, k_, v_)
    db.commit()

    history = db.execute(
        select(KPISnapshot)
        .where(
            KPISnapshot.company_id == company_id,
            KPISnapshot.snapshot_date >= today - timedelta(days=30),
        )
        .order_by(KPISnapshot.snapshot_date)
    ).scalars().all()

    def build(attr):
        series = [float(getattr(h, attr)) for h in history]
        delta = None
        if len(series) >= 2 and series[0] != 0:
            delta = round((series[-1] - series[0]) / abs(series[0]) * 100, 1)
        return {"series": series, "delta_pct": delta}

    return {
        "active_project_count": build("active_project_count"),
        "total_contract_value_try": build("total_contract_value_try"),
        "weighted_avg_margin_pct": build("weighted_avg_margin_pct"),
        "overdue_payment_count": build("overdue_payment_count"),
    }


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
