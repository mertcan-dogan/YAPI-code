"""Projects router: CRUD, project dashboard, budget, company dashboard (Section 2.5, 4.1-4.3)."""
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from slugify import slugify
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calculations.money import D, money, pct, safe_div
from app.constants import COST_CATEGORIES, COST_CATEGORY_KEYS
from app.db import get_db
from app.deps import CurrentUser, DirectorUser
from app.models.budget_line_item import BudgetLineItem
from app.models.project import Project
from app.models.kpi_snapshot import KPISnapshot
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.variation import Variation
from app.responses import APIError, success
from app.schemas.budget import BudgetForecastUpdate, BudgetLineOut
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import financials as fin_service
from app.services import financing as financing_service
from app.services import milestones as milestones_service
from app.services import sales as sales_service
from app.services import units as units_service
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
    # Perf: batch-load every project's cost/invoice/budget rows in 3 queries (not
    # 3×N) — project_financials below then reads them from the per-session cache.
    fin_service.prime_project_inputs(db, projects)
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
    # The `units` schedule is persisted separately (CR-016-B upsert + unit_count
    # derivation), so it is excluded from the column mapping here.
    project = Project(
        company_id=user.company_id,
        **payload.model_dump(exclude={"units"}),
    )
    db.add(project)
    db.flush()
    # Seed budget line items for all categories (Section 11 step 4, optional later edit).
    for cat in COST_CATEGORY_KEYS:
        db.add(BudgetLineItem(project_id=project.id, company_id=user.company_id, cost_category=cat))
    db.flush()
    # CR-016-B: persist the daire dağılımı and derive unit_count from it.
    if payload.units:
        units_service.sync_schedule(db, project, payload.units, user.company_id)
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

    # `units` is upserted separately (CR-016-B); the column mapping excludes it.
    changes = payload.model_dump(exclude_unset=True, exclude={"units"})
    if user.role != ROLE_DIRECTOR:
        allowed = {"completion_pct"}
        # The unit schedule is a project setting → directors only.
        if (set(changes) - allowed) or payload.units is not None:
            raise APIError(403, "FORBIDDEN", "Proje ayarlarını yalnızca yönetici düzenleyebilir")

    old = snapshot(project)
    for k, v in changes.items():
        setattr(project, k, v)
    project.last_modified_by = user.id if hasattr(project, "last_modified_by") else None
    db.flush()
    # CR-016-B: when the units array is provided (even empty), upsert the schedule
    # and re-derive unit_count. When omitted (None), the schedule is left untouched.
    if payload.units is not None:
        units_service.sync_schedule(db, project, payload.units, user.company_id)
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
            # CR-014-C: USD totals = SUM of per-row amount_usd snapshots (§0.2),
            # with a count of rows missing a snapshot. TRY figures unchanged.
            "usd": fin_service.project_usd_totals(db, project),
            # CR-016-B: computed (not stored) residential aggregates over the
            # live unit schedule — feeds CR-017 per-m² benchmarks.
            "residential": _jsonify(units_service.schedule_aggregates(project.units)),
            # CR-015-B: modeled financing cost as a SEPARATE forecast overlay
            # (never an actual cost). Zeroed/empty when the effective toggle is off.
            "financing": financing_service.compute_financing_cost(db, project),
            # CR-019-B: SCHEDULE-lane milestones block (weighted progress, next
            # deadline, overdue count, per-stage). Display + informs Proje
            # Sağlığı's "% Tamamlandı" ONLY — never feeds any money figure (§0.2).
            "milestones": milestones_service.compute_schedule_block(db, project.id, project.company_id),
            # CR-031-C: revenue-model-aware Project P&L (Kar/Zarar) + m² analizi +
            # kur-etkisi. Revenue is sell-side (sales+landowner) OR hakediş per
            # revenue_model — NEVER both (§0.2). Cost is read-only; financing stays
            # a separable overlay (net excl/incl both present).
            "pnl": sales_service.project_pnl(db, project),
            # CR-031-D: IRR (XIRR, TRY & USD) / ROI / süre + yearly cash-flow feed.
            # Dated series over the same lanes; degenerate series → null IRR.
            "investment_return": sales_service.investment_return(db, project),
        }
    )


@router.get("/projects/{project_id}/period-summary")
def project_period_summary(
    project_id: uuid.UUID,
    user: CurrentUser,
    from_date: str,
    to_date: str,
    db: Session = Depends(get_db),
):
    """Activity totals (cost incurred / invoiced / collected + USD) for a date
    range — the dashboard's "Dönem Özeti". Headline KPIs stay full-project; only
    this responds to the range. Company-scoped via get_company_project."""
    project = get_company_project(db, project_id, user)
    try:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
    except (ValueError, TypeError):
        raise APIError(422, "INVALID_DATE", "Geçersiz tarih formatı (YYYY-MM-DD bekleniyor)")
    if start > end:
        raise APIError(422, "INVALID_RANGE", "Başlangıç tarihi bitiş tarihinden sonra olamaz")
    return success(fin_service.period_summary(db, project, start, end))


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


def _budget_breakdown(db, project_ids):
    """Revised budget (original + approved variations) per cost category, summed
    across the given projects.

    `project_ids` MUST be the already role/visibility-scoped active project list
    the dashboard computes (_list_visible_projects), so the breakdown inherits the
    same per-role project visibility — a project manager never sees budget from
    projects they cannot access.

    Returns {"total_try": str, "items": [{category, label_tr, value_try,
    pct_of_total}]} sorted descending by value (TRY as strings via money(), like
    every other dashboard figure). Empty items when there are no budget rows.
    """
    if not project_ids:
        return {"total_try": str(money(D(0))), "items": []}
    rows = db.execute(
        select(
            BudgetLineItem.cost_category,
            func.sum(BudgetLineItem.original_budget_try + BudgetLineItem.approved_variations_try),
        )
        .where(
            BudgetLineItem.project_id.in_(project_ids),
            BudgetLineItem.is_deleted.is_(False),
        )
        .group_by(BudgetLineItem.cost_category)
    ).all()
    # Only positive categories are shown; total = sum of shown bars so the
    # percentages add up to 100% and the footer matches the bars.
    positive = [(cat, val) for cat, val in rows if val and val > 0]
    total = sum((val for _, val in positive), D(0))
    items = [
        {
            "category": cat,
            "label_tr": COST_CATEGORIES.get(cat, cat),
            "value_try": str(money(val)),
            "pct_of_total": str(pct(safe_div(val, total) * 100)),
        }
        for cat, val in positive
    ]
    items.sort(key=lambda x: float(x["value_try"]), reverse=True)
    return {"total_try": str(money(total)), "items": items}


def _variations_net(db, project_ids):
    """Net change-order (Ek İş) value in play across the given projects.

    Approved variations count at their approved value; pending ones at their
    requested value. Rejected/withdrawn are excluded. Scoped by the caller to
    the role/visibility-filtered active projects.
    """
    if not project_ids:
        return D(0)
    rows = db.execute(
        select(Variation.status, Variation.value_try, Variation.approved_value_try).where(
            Variation.project_id.in_(project_ids),
            Variation.is_deleted.is_(False),
            Variation.status.in_(("pending", "approved")),
        )
    ).all()
    total = D(0)
    for status, value, approved in rows:
        if status == "approved":
            total += D(approved if approved is not None else 0)
        else:
            total += D(value or 0)
    return money(total)


@router.get("/dashboard")
def company_dashboard(
    user: CurrentUser,
    db: Session = Depends(get_db),
    project_ids: str | None = Query(None, description="Comma-separated project ids to restrict to."),
    rag: str | None = Query(None, description="Comma-separated RAG statuses (green/amber/red) to restrict to."),
    date_from: str | None = Query(None, description="YYYY-MM-DD; lower bound for the historical cash-flow chart."),
    date_to: str | None = Query(None, description="YYYY-MM-DD; upper bound for the historical cash-flow chart."),
):
    # Role/visibility-scoped active projects, then the optional toolbar filters.
    visible = _list_visible_projects(db, user, only_active=True)
    if project_ids:
        wanted = {x.strip() for x in project_ids.split(",") if x.strip()}
        visible = [p for p in visible if str(p.id) in wanted]
    rag_set = {x.strip().lower() for x in rag.split(",") if x.strip()} if rag else None

    # Compute financials once per project and apply the RAG filter here so every
    # downstream panel (KPIs, charts, tables) reflects the same filtered set.
    # Perf: batch-load all visible projects' inputs in 3 queries (kills the N+1).
    fin_service.prime_project_inputs(db, visible)
    pairs = []
    for p in visible:
        f = fin_service.project_financials(db, p)
        if rag_set and f["rag_status"] not in rag_set:
            continue
        pairs.append((p, f))
    projects = [p for p, _ in pairs]

    rows = []
    total_contract = D(0)
    weighted_margin_num = D(0)
    overdue_total = 0
    # Company-wide financial roll-ups (Ana Sayfa executive band + portfolio budget chart).
    total_invoiced = D(0)
    total_outstanding = D(0)
    total_forecast_cost = D(0)
    total_net_cash = D(0)
    total_revised_budget = D(0)
    total_committed = D(0)
    total_actual = D(0)
    mf_rows = []
    mf_target_num = D(0)
    mf_current_num = D(0)
    mf_contract = D(0)
    portfolio_performance = []

    for p, f in pairs:
        total_contract += f["contract_value_try"]
        weighted_margin_num += f["current_profit_try"]
        overdue_total += f["overdue_count"]
        total_invoiced += f["total_invoiced_try"]
        total_outstanding += f["total_outstanding_try"]
        total_forecast_cost += f["forecast_final_cost_try"]
        total_net_cash += f["net_cash_position_try"]
        total_revised_budget += f["revised_budget_try"]
        total_committed += f["total_committed_try"]
        total_actual += f["total_actual_try"]
        if f["target_margin_pct"] is not None:
            mf_rows.append({
                "name": p.name,
                "target_pct": str(f["target_margin_pct"]),
                "current_pct": str(f["margin_pct"]),
            })
            mf_target_num += f["contract_value_try"] * f["target_margin_pct"]
            mf_current_num += f["current_profit_try"]
            mf_contract += f["contract_value_try"]
        rows.append(
            {
                "id": str(p.id),
                "name": p.name,
                "client_name": p.client_name,
                "contract_value_try": str(f["contract_value_try"]),
                "spent_pct": str(pct(safe_div(f["total_actual_try"], f["revised_budget_try"]) * 100)),
                "completion_pct": str(f["completion_pct"]),
                "margin_pct": str(f["margin_pct"]),
                "margin_try": str(f["current_profit_try"]),
                "net_cash_position_try": str(f["net_cash_position_try"]),
                "rag_status": f["rag_status"],
                "rag_label_tr": f["rag_label_tr"],
                "planned_end_date": p.planned_end_date.isoformat(),
                "overdue": p.planned_end_date < date.today(),
            }
        )
        # Per-project actual vs forecast vs contract (Portföy Performansı chart).
        portfolio_performance.append(
            {
                "project": p.name,
                "contract_try": str(f["contract_value_try"]),
                "actual_try": str(f["total_actual_try"]),
                "forecast_final_try": str(f["forecast_final_cost_try"]),
            }
        )

    weighted_margin = pct(safe_div(weighted_margin_num, total_contract) * 100)

    cashflow_chart = _combined_cashflow_chart(db, [p.id for p in projects])
    if date_from or date_to:
        lo = date_from[:7] if date_from else ""
        hi = date_to[:7] if date_to else "9999-99"
        cashflow_chart = [c for c in cashflow_chart if lo <= c["month"] <= hi]

    ar_aging = _ar_aging(db, [p.id for p in projects], date.today())
    cash_forecast = _cash_forecast(db, [p.id for p in projects], date.today(), total_net_cash)
    mf_rows.sort(key=lambda r: float(r["current_pct"]) - float(r["target_pct"]))
    margin_fade = {
        "has_targets": len(mf_rows) > 0,
        "weighted_target_pct": str(pct(safe_div(mf_target_num, mf_contract))) if mf_contract > 0 else "0",
        "weighted_current_pct": str(pct(safe_div(mf_current_num, mf_contract) * 100)) if mf_contract > 0 else "0",
        "projects": mf_rows,
    }

    variations_net = _variations_net(db, [p.id for p in projects])
    cost_to_complete = money(total_forecast_cost - total_actual)
    # Don't overwrite today's company-wide snapshot with a filtered view; still
    # read history to build trend series.
    filters_active = bool(project_ids or rag or date_from or date_to)
    kpi_trends = _record_and_build_kpi_trends(
        db,
        company_id=user.company_id,
        active_project_count=len(projects),
        total_contract_value=money(total_contract),
        weighted_avg_margin=weighted_margin,
        overdue_payment_count=overdue_total,
        backlog=money(total_contract - total_invoiced),
        projected_profit=money(total_contract - total_forecast_cost),
        total_receivables=money(total_outstanding),
        net_cash=money(total_net_cash),
        cost_to_complete=cost_to_complete,
        variations_net=variations_net,
        record=not filters_active,
    )

    return success(
        {
            "kpis": {
                "active_project_count": len(projects),
                "total_contract_value_try": str(money(total_contract)),
                "weighted_avg_margin_pct": str(weighted_margin),
                "overdue_payment_count": overdue_total,
                # Cost to complete = forecast final cost - actual cost-to-date.
                "cost_to_complete_try": str(cost_to_complete),
                # Ek İşler (Net) — approved + pending change-order value in play.
                "variations_net_try": str(variations_net),
            },
            "kpi_trends": kpi_trends,
            "exec_kpis": {
                # Backlog = remaining (unbilled) contract revenue across active projects.
                "backlog_try": str(money(total_contract - total_invoiced)),
                # Projected profit at completion = contract - forecast final cost.
                "projected_profit_try": str(money(total_contract - total_forecast_cost)),
                "total_receivables_try": str(money(total_outstanding)),
                "net_cash_position_try": str(money(total_net_cash)),
            },
            # CR-014-C: portfolio USD totals = SUM of per-row amount_usd snapshots
            # over the same filtered project set (§0.2), each with a missing-snapshot
            # count. NOT total_try ÷ today's rate. TRY figures unchanged.
            "usd": fin_service.usd_aggregates(db, project_ids=[p.id for p in projects]),
            "ar_aging": ar_aging,
            "margin_fade": margin_fade,
            "cash_forecast": cash_forecast,
            "portfolio_budget": {
                "contract_try": str(money(total_contract)),
                "revised_budget_try": str(money(total_revised_budget)),
                "committed_try": str(money(total_committed)),
                "actual_try": str(money(total_actual)),
                "forecast_final_cost_try": str(money(total_forecast_cost)),
            },
            # Scoped to the same visible active projects (per-role visibility).
            "budget_breakdown": _budget_breakdown(db, [p.id for p in projects]),
            # Per-project actual vs forecast vs contract (Portföy Performansı chart).
            "portfolio_performance": portfolio_performance,
            "projects": rows,
            "cashflow_chart": cashflow_chart,
        }
    )


@router.get("/dashboard/document-feed")
def dashboard_document_feed(
    user: CurrentUser, db: Session = Depends(get_db), limit: int = Query(12, le=50)
):
    """Gelen Belgeler feed — recent supplier invoices (Faturalar), client
    applications for payment (Hakedişler), and variations/claims (Ek İşler),
    scoped to the user's visible projects.

    NOTE: there is no document-ingestion table that stores an AI-classification /
    Extracted-vs-Under-Review status, so this feed surfaces the real domain
    records and their real statuses only (no fabricated AI status).
    """
    projects = _list_visible_projects(db, user)
    ids = [p.id for p in projects]
    name_by_id = {p.id: p.name for p in projects}
    if not ids:
        return success({"faturalar": [], "hakedisler": [], "ek_isler": []})

    cost_rows = db.execute(
        select(CostEntry)
        .where(CostEntry.project_id.in_(ids), CostEntry.is_deleted.is_(False))
        .order_by(CostEntry.entry_date.desc())
        .limit(limit)
    ).scalars().all()
    faturalar = [
        {
            "id": str(c.id),
            "label": c.invoice_number or c.supplier_name or "Fatura",
            "source": c.supplier_name,
            "project": name_by_id.get(c.project_id),
            "category": c.cost_category,
            "amount_try": str(money(D(c.total_with_vat_try))),
            "status": "incelemede" if c.pending_approval else c.payment_status,
            "date": c.entry_date.isoformat(),
        }
        for c in cost_rows
    ]

    inv_rows = db.execute(
        select(ClientInvoice)
        .where(ClientInvoice.project_id.in_(ids), ClientInvoice.is_deleted.is_(False))
        .order_by(ClientInvoice.invoice_date.desc())
        .limit(limit)
    ).scalars().all()
    hakedisler = [
        {
            "id": str(i.id),
            "label": i.invoice_number,
            "source": i.hakkedis_period,
            "project": name_by_id.get(i.project_id),
            "amount_try": str(money(D(i.total_with_vat_try))),
            "status": i.payment_status,
            "date": i.invoice_date.isoformat(),
        }
        for i in inv_rows
    ]

    var_rows = db.execute(
        select(Variation)
        .where(Variation.project_id.in_(ids), Variation.is_deleted.is_(False))
        .order_by(Variation.submitted_date.desc())
        .limit(limit)
    ).scalars().all()
    ek_isler = [
        {
            "id": str(v.id),
            "label": v.variation_number,
            "title": v.title,
            "project": name_by_id.get(v.project_id),
            "amount_try": str(
                money(D(v.approved_value_try if v.status == "approved" and v.approved_value_try is not None else v.value_try))
            ),
            "status": v.status,
            "date": v.submitted_date.isoformat(),
        }
        for v in var_rows
    ]

    return success({"faturalar": faturalar, "hakedisler": hakedisler, "ek_isler": ek_isler})


def _cash_forecast(db, project_ids, today, starting_cash, months=6):
    """6-month forward cash projection: expected inflows (unpaid invoices by due
    date) vs outflows (unpaid costs by due date), with a running cash line.

    Overdue items (due before this month) land in the first bucket. Items past
    the horizon are ignored.
    """
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    idx = {k: i for i, k in enumerate(keys)}
    cur_first = today.replace(day=1)
    inflow = [D(0)] * months
    outflow = [D(0)] * months

    def bucket(d):
        if d is None:
            return None
        if d < cur_first:
            return 0
        return idx.get(f"{d.year:04d}-{d.month:02d}")

    if project_ids:
        for inv in db.execute(
            select(ClientInvoice).where(ClientInvoice.project_id.in_(project_ids), ClientInvoice.is_deleted.is_(False))
        ).scalars().all():
            out = D(inv.outstanding_try)
            if out <= 0:
                continue
            b = bucket(inv.due_date)
            if b is not None:
                inflow[b] += out
        for c in db.execute(
            select(CostEntry).where(
                CostEntry.project_id.in_(project_ids),
                CostEntry.is_deleted.is_(False),
                CostEntry.pending_approval.is_(False),
            )
        ).scalars().all():
            unpaid = D(c.amount_try) - D(c.amount_paid_try)
            if unpaid <= 0:
                continue
            b = bucket(c.payment_due_date)
            if b is not None:
                outflow[b] += unpaid

    out_months = []
    cum = D(starting_cash)
    min_cash = None
    min_month = None
    for i, k in enumerate(keys):
        net = inflow[i] - outflow[i]
        cum += net
        if min_cash is None or cum < min_cash:
            min_cash = cum
            min_month = k
        out_months.append({
            "month": k,
            "inflow_try": str(money(inflow[i])),
            "outflow_try": str(money(outflow[i])),
            "net_try": str(money(net)),
            "cumulative_try": str(money(cum)),
        })
    return {
        "starting_cash_try": str(money(D(starting_cash))),
        "months": out_months,
        "min_cash_try": str(money(min_cash)) if min_cash is not None else "0",
        "min_cash_month": min_month,
        "shortfall": bool(min_cash is not None and min_cash < 0),
    }


def _ar_aging(db, project_ids, today):
    """Receivables aging buckets + DSO (avg collection period), over active projects.

    Buckets by days past due_date; DSO = outstanding-weighted average age since
    invoice_date (real, computed from the ledger). Returns None DSO if no AR.
    """
    if not project_ids:
        return {"not_due_try": "0", "d1_30_try": "0", "d31_60_try": "0", "d60_plus_try": "0", "total_outstanding_try": "0", "dso_days": None}
    invs = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.project_id.in_(project_ids),
            ClientInvoice.is_deleted.is_(False),
        )
    ).scalars().all()
    b = {"not_due": D(0), "d1_30": D(0), "d31_60": D(0), "d60_plus": D(0)}
    total = D(0)
    weighted_age = D(0)
    for i in invs:
        out = D(i.outstanding_try)
        if out <= 0:
            continue
        total += out
        overdue = (today - i.due_date).days
        if overdue <= 0:
            b["not_due"] += out
        elif overdue <= 30:
            b["d1_30"] += out
        elif overdue <= 60:
            b["d31_60"] += out
        else:
            b["d60_plus"] += out
        weighted_age += out * D((today - i.invoice_date).days)
    dso = int(round(float(weighted_age / total))) if total > 0 else None
    return {
        "not_due_try": str(money(b["not_due"])),
        "d1_30_try": str(money(b["d1_30"])),
        "d31_60_try": str(money(b["d31_60"])),
        "d60_plus_try": str(money(b["d60_plus"])),
        "total_outstanding_try": str(money(total)),
        "dso_days": dso,
    }


def _record_and_build_kpi_trends(db, *, company_id, active_project_count, total_contract_value, weighted_avg_margin, overdue_payment_count, backlog, projected_profit, total_receivables, net_cash, cost_to_complete, variations_net, record=True):
    """Upsert today's KPI snapshot, then return real trend series + deltas.

    Series/deltas are based purely on recorded daily snapshots — they stay empty
    until at least two distinct days exist, so nothing is ever fabricated. When
    ``record`` is False (a filtered dashboard view) the snapshot is not written —
    the company-wide history must not be overwritten with a filtered total — but
    the trend series are still built from existing history.
    """
    today = date.today()
    if record:
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
            backlog_try=backlog,
            projected_profit_try=projected_profit,
            total_receivables_try=total_receivables,
            net_cash_position_try=net_cash,
            cost_to_complete_try=cost_to_complete,
            variations_net_try=variations_net,
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
            KPISnapshot.snapshot_date >= today - timedelta(days=140),
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
        "backlog_try": build("backlog_try"),
        "projected_profit_try": build("projected_profit_try"),
        "total_receivables_try": build("total_receivables_try"),
        "net_cash_position_try": build("net_cash_position_try"),
        "cost_to_complete_try": build("cost_to_complete_try"),
        "variations_net_try": build("variations_net_try"),
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
