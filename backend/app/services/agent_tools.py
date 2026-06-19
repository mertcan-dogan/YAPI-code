"""CR-007-A — Read-only agent tool catalogue (data layer).

Each tool is a parameterised, ``company_id``-scoped SQL query the AI agent may
call. The governing principle (CR-007 §1.2): **PostgreSQL computes, the LLM only
narrates.** Therefore:

* Every figure returned here is produced by a SQL ``SUM``/``COUNT``/``AVG`` — never
  a Python loop the model could influence (the few Python folds below operate
  only on values already aggregated by SQL).
* Tools are **READ-ONLY** — no INSERT/UPDATE/DELETE path exists.
* ``company_id`` is injected by the executor from the authenticated user and is
  applied in every ``WHERE`` clause. The backend runs under the Supabase service
  role (bypassing RLS), so this filter is the real isolation boundary.
* There is **no raw-SQL tool** — only the fixed functions in this module.

Return shape (every tool): ``{summary, records, row_count, truncated}``. Records
carry their ``id`` and a ``deep_link`` for citation (CR-007-H wires the
page-side ``?highlight=`` handling).

This file covers the non-vendor tools. ``get_vendor_spend`` / ``compare_vendors``
land in CR-007-D and ``create_chart`` in CR-007-C; the shared helpers they need
(``month_bucket``, ``normalize_vendor_name``) live here.
"""
import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.calculations.money import D, money
from app.constants import COST_CATEGORIES, PROJECT_TYPES
from app.models.ai_alert import AIAlert
from app.models.budget_line_item import BudgetLineItem
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.equipment_log import EquipmentLog
from app.models.project import Project
from app.models.subcontractor import Subcontractor
from app.models.vendor import Vendor, VendorAlias

# At most this many raw records are returned; beyond it we set truncated=True and
# rely on the aggregated summary (§2.2).
MAX_RECORDS = 500


class ToolError(Exception):
    """Raised when a tool cannot run (e.g. unknown project_id). The executor
    (CR-007-B) turns this into a Turkish tool_result error for the model."""


# --------------------------------------------------------------------------- #
# Tool: create_chart (CR-007-C) — does NOT query data
# --------------------------------------------------------------------------- #
def create_chart(**spec) -> dict:
    """Validate a chart spec the agent built from data it already fetched.

    This tool performs no DB access — it only validates against the strict
    ``ChartSpec`` schema (CR-007-C), filling default Yapı palette colours and
    coercing numeric strings. Malformed/empty specs are rejected so the model
    cannot invent chart data. Raises ToolError (Turkish) on validation failure.
    """
    from app.schemas.chart import ChartSpec, ValidationError

    try:
        validated = ChartSpec(**spec)
    except ValidationError as exc:
        msgs = "; ".join(e.get("msg", "") for e in exc.errors())
        raise ToolError(f"Geçersiz grafik tanımı: {msgs}") from exc
    except TypeError as exc:  # unexpected/missing top-level fields
        raise ToolError(f"Geçersiz grafik tanımı: {exc}") from exc
    return validated.model_dump()


# --------------------------------------------------------------------------- #
# Dialect-aware + normalisation helpers (§2.3, §0 B1)
# --------------------------------------------------------------------------- #
def month_bucket(db: Session, col):
    """``date_trunc('month', col)`` on PostgreSQL, ``strftime('%Y-%m-01', col)``
    on SQLite. Never hard-code ``date_trunc`` — it breaks the SQLite test DB."""
    if db.get_bind().dialect.name == "postgresql":
        return func.date_trunc("month", col)
    return func.strftime("%Y-%m-01", col)


def _month_key(value) -> str | None:
    """Normalise a month-bucket value to 'YYYY-MM' regardless of dialect.

    PostgreSQL returns a ``datetime`` (-> '2026-01-01 00:00:00'); SQLite returns
    the string '2026-01-01'. Slicing the first 7 chars yields 'YYYY-MM' for both.
    """
    if value is None:
        return None
    return str(value)[:7]


_SUFFIX_RE = re.compile(r"\b(A\.?Ş\.?|LTD\.?|ŞTİ\.?|STI\.?|SAN\.?|TİC\.?|TIC\.?|INC\.?|LLC\.?)\b")
_TR_UPPER = str.maketrans({"i": "İ", "ı": "I", "ş": "Ş", "ğ": "Ğ", "ü": "Ü", "ö": "Ö", "ç": "Ç"})


def normalize_vendor_name(name: str | None) -> str:
    """Trim, collapse whitespace, uppercase (Turkish-aware), strip company
    suffixes and punctuation. Used by the vendor tools (CR-007-D) so the same
    firm spelled differently in ``cost_entries.supplier_name`` and
    ``subcontractors.name`` collapses to one key on SQLite (where pg_trgm is
    unavailable). The pg_trgm fuzzy path is added in CR-007-D for prod."""
    if not name:
        return ""
    s = name.strip().translate(_TR_UPPER).upper()
    s = _SUFFIX_RE.sub("", s)
    s = s.replace(".", " ").replace(",", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _deep_link(kind: str, project_id, record_id) -> str:
    """Citable URL for a record. Page-side ``?highlight=`` handling is built in
    CR-007-H §9.0; this just emits the target. Client invoices have a real list
    page; cost entries surface through the dashboard's CostEntriesDrawer."""
    pid, rid = str(project_id), str(record_id)
    if kind == "client_invoice":
        return f"/projects/{pid}/invoices?highlight={rid}"
    if kind == "cost_entry":
        return f"/projects/{pid}/dashboard?highlight={rid}"
    if kind == "subcontractor":
        return f"/projects/{pid}/subcontractors?highlight={rid}"
    if kind == "equipment":
        return f"/projects/{pid}/equipment?highlight={rid}"
    return f"/projects/{pid}/dashboard"


def _s(value) -> str:
    """Money value -> quantised string ('12345.67'). Numbers stay exact (kuruş)."""
    return str(money(value))


def _company_projects(db: Session, company_id) -> dict[uuid.UUID, Project]:
    rows = db.execute(
        select(Project).where(
            Project.company_id == company_id, Project.is_deleted.is_(False)
        )
    ).scalars().all()
    return {p.id: p for p in rows}


def _require_project(db: Session, company_id, project_id) -> Project:
    if project_id is None:
        raise ToolError("project_id gerekli")
    p = db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.company_id == company_id,
            Project.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if p is None:
        raise ToolError("Proje bulunamadı")
    return p


# --------------------------------------------------------------------------- #
# Tool: list_projects
# --------------------------------------------------------------------------- #
def list_projects(db: Session, company_id, status: str | None = None) -> dict:
    """Portfolio summary: one record per project + portfolio aggregates."""
    q = select(Project).where(
        Project.company_id == company_id, Project.is_deleted.is_(False)
    )
    if status:
        q = q.where(Project.status == status)
    projects = db.execute(q.order_by(Project.created_at)).scalars().all()

    records = []
    by_status: dict[str, int] = {}
    total_contract = D(0)
    for p in projects:
        by_status[p.status] = by_status.get(p.status, 0) + 1
        total_contract += D(p.contract_value_try)
        records.append({
            "id": str(p.id),
            "name": p.name,
            "project_code": p.project_code,
            "project_type": PROJECT_TYPES.get(p.project_type, p.project_type),
            "status": p.status,
            "contract_value_try": _s(p.contract_value_try),
            "completion_pct": _s(p.completion_pct),
            "deep_link": _deep_link("project", p.id, p.id),
        })

    return {
        "summary": {
            "project_count": len(projects),
            "total_contract_value_try": _s(total_contract),
            "by_status": by_status,
        },
        "records": records[:MAX_RECORDS],
        "row_count": len(records),
        "truncated": len(records) > MAX_RECORDS,
    }


# --------------------------------------------------------------------------- #
# Tool: get_project_financials (reuse dashboard logic — api/projects.py:141)
# --------------------------------------------------------------------------- #
def get_project_financials(db: Session, company_id, project_id) -> dict:
    """Full computed KPI summary for one project. Reuses the same service the
    /projects/{id}/dashboard endpoint uses, so the agent's numbers match the
    dashboard exactly."""
    from app.services import financials as fin

    project = _require_project(db, company_id, project_id)
    f = fin.project_financials(db, project)
    fac = fin.forecast_at_completion(db, project)

    # f holds Decimals/ints; stringify Decimals for JSON-safe, exact transport.
    summary = {k: (str(v) if hasattr(v, "quantize") else v) for k, v in f.items()}
    summary.update({
        "project_id": str(project.id),
        "project_name": project.name,
        "forecast_at_completion": fac,
        "deep_link": _deep_link("project", project.id, project.id),
    })
    return {"summary": summary, "records": [], "row_count": 0, "truncated": False}


# --------------------------------------------------------------------------- #
# Tool: query_cost_entries
# --------------------------------------------------------------------------- #
def _cost_base_filters(company_id, project_id, date_from, date_to, cost_category,
                       supplier_name, subcontractor_id, payment_status, entry_type):
    conds = [
        CostEntry.company_id == company_id,
        CostEntry.is_deleted.is_(False),
        # Match the dashboards: unapproved (CR-003-J) costs are excluded.
        CostEntry.pending_approval.is_(False),
    ]
    if project_id is not None:
        conds.append(CostEntry.project_id == project_id)
    if date_from is not None:
        conds.append(CostEntry.entry_date >= date_from)
    if date_to is not None:
        conds.append(CostEntry.entry_date <= date_to)
    if cost_category:
        conds.append(CostEntry.cost_category == cost_category)
    if supplier_name:
        conds.append(CostEntry.supplier_name.ilike(f"%{supplier_name}%"))
    if subcontractor_id is not None:
        conds.append(CostEntry.subcontractor_id == subcontractor_id)
    if payment_status:
        conds.append(CostEntry.payment_status == payment_status)
    if entry_type:
        conds.append(CostEntry.entry_type == entry_type)
    return conds


def query_cost_entries(
    db: Session, company_id, *, project_id=None, date_from: date | None = None,
    date_to: date | None = None, cost_category: str | None = None,
    supplier_name: str | None = None, subcontractor_id=None,
    payment_status: str | None = None, entry_type: str | None = None,
    group_by: str | None = None,
) -> dict:
    """Supplier-cost (maliyet) records + SQL aggregates, optionally grouped."""
    conds = _cost_base_filters(
        company_id, project_id, date_from, date_to, cost_category,
        supplier_name, subcontractor_id, payment_status, entry_type,
    )

    totals = db.execute(
        select(
            func.coalesce(func.sum(CostEntry.amount_try), 0),
            func.coalesce(func.sum(CostEntry.total_with_vat_try), 0),
            func.count(CostEntry.id),
        ).where(*conds)
    ).one()

    summary: dict = {
        "total_amount_try": _s(totals[0]),
        "total_with_vat_try": _s(totals[1]),
        "entry_count": int(totals[2]),
    }

    if group_by:
        summary["groups"] = _grouped_costs(db, conds, group_by)

    rows = db.execute(
        select(CostEntry).where(*conds).order_by(CostEntry.entry_date.desc()).limit(MAX_RECORDS + 1)
    ).scalars().all()
    truncated = len(rows) > MAX_RECORDS
    records = [{
        "id": str(c.id),
        "project_id": str(c.project_id),
        "entry_date": c.entry_date.isoformat() if c.entry_date else None,
        "cost_category": c.cost_category,
        "supplier_name": c.supplier_name,
        "amount_try": _s(c.amount_try),
        "total_with_vat_try": _s(c.total_with_vat_try),
        "payment_status": c.payment_status,
        "entry_type": c.entry_type,
        "deep_link": _deep_link("cost_entry", c.project_id, c.id),
    } for c in rows[:MAX_RECORDS]]

    return {"summary": summary, "records": records, "row_count": len(records), "truncated": truncated}


def _grouped_costs(db: Session, conds, group_by: str) -> list[dict]:
    if group_by == "month":
        key = month_bucket(db, CostEntry.entry_date)
        label_fn = _month_key
    elif group_by == "category":
        key = CostEntry.cost_category
        label_fn = lambda v: COST_CATEGORIES.get(v, v)  # noqa: E731
    elif group_by == "supplier":
        key = CostEntry.supplier_name
        label_fn = lambda v: v  # noqa: E731
    elif group_by == "project":
        key = CostEntry.project_id
        label_fn = lambda v: str(v)  # noqa: E731
    else:
        raise ToolError(f"Geçersiz group_by: {group_by}")

    rows = db.execute(
        select(
            key,
            func.coalesce(func.sum(CostEntry.amount_try), 0),
            func.coalesce(func.sum(CostEntry.total_with_vat_try), 0),
            func.count(CostEntry.id),
        ).where(*conds).group_by(key).order_by(key)
    ).all()
    return [{
        "key": _month_key(r[0]) if group_by == "month" else (str(r[0]) if r[0] is not None else None),
        "label": label_fn(r[0]) if r[0] is not None else None,
        "total_amount_try": _s(r[1]),
        "total_with_vat_try": _s(r[2]),
        "count": int(r[3]),
    } for r in rows]


# --------------------------------------------------------------------------- #
# Tool: query_client_invoices
# --------------------------------------------------------------------------- #
def query_client_invoices(
    db: Session, company_id, *, project_id=None, date_from: date | None = None,
    date_to: date | None = None, payment_status: str | None = None,
    invoice_type: str | None = None, group_by: str | None = None,
) -> dict:
    """Hakediş / client invoices + SQL aggregates, optionally grouped."""
    conds = [
        ClientInvoice.company_id == company_id,
        ClientInvoice.is_deleted.is_(False),
    ]
    if project_id is not None:
        conds.append(ClientInvoice.project_id == project_id)
    if date_from is not None:
        conds.append(ClientInvoice.invoice_date >= date_from)
    if date_to is not None:
        conds.append(ClientInvoice.invoice_date <= date_to)
    if payment_status:
        conds.append(ClientInvoice.payment_status == payment_status)
    if invoice_type:
        conds.append(ClientInvoice.invoice_type == invoice_type)

    totals = db.execute(
        select(
            func.coalesce(func.sum(ClientInvoice.amount_try), 0),
            func.coalesce(func.sum(ClientInvoice.total_with_vat_try), 0),
            func.coalesce(func.sum(ClientInvoice.net_due_try), 0),
            func.coalesce(func.sum(ClientInvoice.amount_received_try), 0),
            func.count(ClientInvoice.id),
        ).where(*conds)
    ).one()

    summary: dict = {
        "total_amount_try": _s(totals[0]),
        "total_with_vat_try": _s(totals[1]),
        "total_net_due_try": _s(totals[2]),
        "total_received_try": _s(totals[3]),
        "total_outstanding_try": _s(D(totals[2]) - D(totals[3])),
        "invoice_count": int(totals[4]),
    }

    if group_by:
        summary["groups"] = _grouped_invoices(db, conds, group_by)

    rows = db.execute(
        select(ClientInvoice).where(*conds).order_by(ClientInvoice.invoice_date.desc()).limit(MAX_RECORDS + 1)
    ).scalars().all()
    truncated = len(rows) > MAX_RECORDS
    records = [{
        "id": str(i.id),
        "project_id": str(i.project_id),
        "invoice_number": i.invoice_number,
        "invoice_date": i.invoice_date.isoformat() if i.invoice_date else None,
        "invoice_type": i.invoice_type,
        "amount_try": _s(i.amount_try),
        "total_with_vat_try": _s(i.total_with_vat_try),
        "net_due_try": _s(i.net_due_try),
        "outstanding_try": _s(i.outstanding_try),
        "payment_status": i.payment_status,
        "deep_link": _deep_link("client_invoice", i.project_id, i.id),
    } for i in rows[:MAX_RECORDS]]

    return {"summary": summary, "records": records, "row_count": len(records), "truncated": truncated}


def _grouped_invoices(db: Session, conds, group_by: str) -> list[dict]:
    if group_by == "month":
        key = month_bucket(db, ClientInvoice.invoice_date)
    elif group_by == "type":
        key = ClientInvoice.invoice_type
    elif group_by == "status":
        key = ClientInvoice.payment_status
    elif group_by == "project":
        key = ClientInvoice.project_id
    else:
        raise ToolError(f"Geçersiz group_by: {group_by}")

    rows = db.execute(
        select(
            key,
            func.coalesce(func.sum(ClientInvoice.total_with_vat_try), 0),
            func.coalesce(func.sum(ClientInvoice.net_due_try), 0),
            func.count(ClientInvoice.id),
        ).where(*conds).group_by(key).order_by(key)
    ).all()
    return [{
        "key": _month_key(r[0]) if group_by == "month" else (str(r[0]) if r[0] is not None else None),
        "total_with_vat_try": _s(r[1]),
        "total_net_due_try": _s(r[2]),
        "count": int(r[3]),
    } for r in rows]


# --------------------------------------------------------------------------- #
# Tool: query_subcontractors
# --------------------------------------------------------------------------- #
def query_subcontractors(db: Session, company_id, *, project_id=None, name: str | None = None) -> dict:
    """Subcontractor contracts with value, paid-to-date, retention and remaining
    commitment. ``paid`` is summed from linked cost entries in SQL."""
    conds = [
        Subcontractor.company_id == company_id,
        Subcontractor.is_deleted.is_(False),
    ]
    if project_id is not None:
        conds.append(Subcontractor.project_id == project_id)
    if name:
        conds.append(Subcontractor.name.ilike(f"%{name}%"))

    subs = db.execute(select(Subcontractor).where(*conds).order_by(Subcontractor.name)).scalars().all()

    # Paid-to-date per subcontractor, aggregated in SQL (one grouped query).
    paid_map: dict[uuid.UUID, object] = {}
    if subs:
        paid_rows = db.execute(
            select(
                CostEntry.subcontractor_id,
                func.coalesce(func.sum(CostEntry.amount_paid_try), 0),
            ).where(
                CostEntry.company_id == company_id,
                CostEntry.is_deleted.is_(False),
                CostEntry.subcontractor_id.in_([s.id for s in subs]),
            ).group_by(CostEntry.subcontractor_id)
        ).all()
        paid_map = {r[0]: r[1] for r in paid_rows}

    records = []
    tot_committed = D(0)
    tot_paid = D(0)
    tot_remaining = D(0)
    tot_retention = D(0)
    for s in subs:
        committed = D(s.contract_value_try) + D(s.approved_variations_try)
        paid = D(paid_map.get(s.id, 0))
        remaining = committed - paid
        retention = committed * D(s.retention_pct) / D(100)
        tot_committed += committed
        tot_paid += paid
        tot_remaining += remaining
        tot_retention += retention
        records.append({
            "id": str(s.id),
            "project_id": str(s.project_id),
            "name": s.name,
            "status": s.status,
            "contract_value_try": _s(s.contract_value_try),
            "approved_variations_try": _s(s.approved_variations_try),
            "total_committed_try": _s(committed),
            "paid_to_date_try": _s(paid),
            "remaining_commitment_try": _s(remaining),
            "retention_pct": _s(s.retention_pct),
            "retention_amount_try": _s(retention),
            "deep_link": _deep_link("subcontractor", s.project_id, s.id),
        })

    return {
        "summary": {
            "subcontractor_count": len(subs),
            "total_committed_try": _s(tot_committed),
            "total_paid_try": _s(tot_paid),
            "total_remaining_try": _s(tot_remaining),
            "total_retention_try": _s(tot_retention),
        },
        "records": records[:MAX_RECORDS],
        "row_count": len(records),
        "truncated": len(records) > MAX_RECORDS,
    }


# --------------------------------------------------------------------------- #
# Tool: get_cashflow (reuse financials.py / cashflow.py)
# --------------------------------------------------------------------------- #
def get_cashflow(db: Session, company_id, *, project_id=None, window_days: int | None = None,
                 today: date | None = None) -> dict:
    """Monthly inflow/outflow series + 30/60/90-day cash-need projection.

    Reuses the same calculation engine as the dashboards so figures match. With
    ``project_id`` it is one project; without, it sums across the portfolio."""
    from app.services import financials as fin

    if project_id is not None:
        projects = [_require_project(db, company_id, project_id)]
    else:
        projects = list(_company_projects(db, company_id).values())

    # Sum the monthly series across projects by month key.
    series_map: dict[str, dict] = {}
    proj_for_window = None
    for p in projects:
        proj_for_window = p
        for row in fin.project_cashflow(db, p, today=today):
            k = row["month"]
            agg = series_map.setdefault(k, {
                "month": k, "planned_out_try": D(0), "actual_out_try": D(0),
                "planned_in_try": D(0), "actual_in_try": D(0), "net_try": D(0),
            })
            for f in ("planned_out_try", "actual_out_try", "planned_in_try", "actual_in_try", "net_try"):
                agg[f] += D(row[f])

    series = []
    for k in sorted(series_map):
        a = series_map[k]
        series.append({f: (a[f] if f == "month" else _s(a[f])) for f in a})

    # 30/60/90 projection. For a single project, reuse cash_need_windows; for the
    # portfolio, sum the per-project windows by horizon.
    proj_windows: dict[int, dict] = {}
    for p in projects:
        for w in fin.cash_need_windows(db, p, today=today):
            agg = proj_windows.setdefault(w["days"], {
                "days": w["days"], "planned_out_try": D(0),
                "expected_in_try": D(0), "net_need_try": D(0),
            })
            agg["planned_out_try"] += D(w["planned_out_try"])
            agg["expected_in_try"] += D(w["expected_in_try"])
            agg["net_need_try"] += D(w["net_need_try"])
    projection = []
    for days in sorted(proj_windows):
        a = proj_windows[days]
        projection.append({
            "days": days,
            "planned_out_try": _s(a["planned_out_try"]),
            "expected_in_try": _s(a["expected_in_try"]),
            "net_need_try": _s(a["net_need_try"]),
            "shortfall": a["net_need_try"] > 0,
        })

    summary = {
        "project_count": len(projects),
        "projection": projection,
    }
    if window_days in (30, 60, 90):
        summary["focus_window"] = next((w for w in projection if w["days"] == window_days), None)

    deep_link = _deep_link("project", proj_for_window.id, proj_for_window.id).replace(
        "/dashboard", "/cashflow"
    ) if (project_id is not None and proj_for_window) else None

    return {
        "summary": summary,
        "records": series,
        "row_count": len(series),
        "truncated": False,
        "deep_link": deep_link,
    }


# --------------------------------------------------------------------------- #
# Tool: get_overdue_payments
# --------------------------------------------------------------------------- #
def get_overdue_payments(db: Session, company_id, *, project_id=None, today: date | None = None) -> dict:
    """Overdue payables (supplier costs past due, unpaid) + receivables (client
    invoices past due, outstanding)."""
    today = today or date.today()

    pay_conds = [
        CostEntry.company_id == company_id,
        CostEntry.is_deleted.is_(False),
        CostEntry.pending_approval.is_(False),
        CostEntry.payment_status != "paid",
        CostEntry.payment_due_date.is_not(None),
        CostEntry.payment_due_date < today,
    ]
    if project_id is not None:
        pay_conds.append(CostEntry.project_id == project_id)
    payables = db.execute(
        select(CostEntry).where(*pay_conds).order_by(CostEntry.payment_due_date)
    ).scalars().all()

    rec_conds = [
        ClientInvoice.company_id == company_id,
        ClientInvoice.is_deleted.is_(False),
        ClientInvoice.payment_status != "paid",
        ClientInvoice.due_date < today,
        ClientInvoice.outstanding_try > 0,
    ]
    if project_id is not None:
        rec_conds.append(ClientInvoice.project_id == project_id)
    receivables = db.execute(
        select(ClientInvoice).where(*rec_conds).order_by(ClientInvoice.due_date)
    ).scalars().all()

    pay_records = []
    pay_total = D(0)
    for c in payables:
        remaining = D(c.total_with_vat_try) - D(c.amount_paid_try)
        pay_total += remaining
        pay_records.append({
            "id": str(c.id),
            "type": "payable",
            "project_id": str(c.project_id),
            "supplier_name": c.supplier_name,
            "remaining_try": _s(remaining),
            "payment_due_date": c.payment_due_date.isoformat() if c.payment_due_date else None,
            "deep_link": _deep_link("cost_entry", c.project_id, c.id),
        })

    rec_records = []
    rec_total = D(0)
    for i in receivables:
        outstanding = D(i.outstanding_try)
        rec_total += outstanding
        rec_records.append({
            "id": str(i.id),
            "type": "receivable",
            "project_id": str(i.project_id),
            "invoice_number": i.invoice_number,
            "outstanding_try": _s(outstanding),
            "due_date": i.due_date.isoformat() if i.due_date else None,
            "deep_link": _deep_link("client_invoice", i.project_id, i.id),
        })

    records = pay_records + rec_records
    return {
        "summary": {
            "overdue_payable_total_try": _s(pay_total),
            "overdue_payable_count": len(pay_records),
            "overdue_receivable_total_try": _s(rec_total),
            "overdue_receivable_count": len(rec_records),
        },
        "records": records[:MAX_RECORDS],
        "row_count": len(records),
        "truncated": len(records) > MAX_RECORDS,
    }


# --------------------------------------------------------------------------- #
# CR-007-D — Vendor spend & compare (headline use case)
# --------------------------------------------------------------------------- #
PG_TRGM_THRESHOLD = 0.4


def _names_match(target_norm: str, candidate: str | None) -> bool:
    """Portable match used on every dialect: normalised equality or substring
    containment either way. On PostgreSQL this is augmented by pg_trgm in
    ``_matching_vendors`` (§2.3)."""
    if not candidate or not target_norm:
        return False
    cand = normalize_vendor_name(candidate)
    if not cand:
        return False
    return cand == target_norm or target_norm in cand or cand in target_norm


def _matching_vendors(db: Session, company_id, vendor_name: str):
    """Resolve a free-text vendor name to the concrete supplier-name strings and
    subcontractor ids it matches, unioning both sources (§5.2). Returns
    ``(supplier_names:set, subcontractor_ids:set, matched_display_names:sorted)``.

    Matching (the only Python step) determines the *filter set*; all money is then
    summed by SQL, honouring §1.2. On PostgreSQL pg_trgm similarity widens the
    match; on SQLite the portable normalised path is used.
    """
    target = normalize_vendor_name(vendor_name)
    matched_suppliers: set[str] = set()
    matched_sub_ids: set = set()
    matched_names: set[str] = set()

    supplier_rows = db.execute(
        select(CostEntry.supplier_name).where(
            CostEntry.company_id == company_id,
            CostEntry.is_deleted.is_(False),
            CostEntry.supplier_name.is_not(None),
        ).distinct()
    ).all()
    for (name,) in supplier_rows:
        if _names_match(target, name):
            matched_suppliers.add(name)
            matched_names.add(name)

    sub_rows = db.execute(
        select(Subcontractor.id, Subcontractor.name).where(
            Subcontractor.company_id == company_id,
            Subcontractor.is_deleted.is_(False),
        )
    ).all()
    for sid, name in sub_rows:
        if _names_match(target, name):
            matched_sub_ids.add(sid)
            matched_names.add(name)

    # PostgreSQL only: widen with pg_trgm fuzzy matches (tested behind
    # @pytest.mark.postgres; the extension is enabled by migration 0021).
    if db.get_bind().dialect.name == "postgresql":
        sim = func.similarity
        for (name,) in db.execute(
            select(CostEntry.supplier_name).where(
                CostEntry.company_id == company_id,
                CostEntry.is_deleted.is_(False),
                CostEntry.supplier_name.is_not(None),
                sim(CostEntry.supplier_name, vendor_name) >= PG_TRGM_THRESHOLD,
            ).distinct()
        ).all():
            matched_suppliers.add(name)
            matched_names.add(name)
        for sid, name in db.execute(
            select(Subcontractor.id, Subcontractor.name).where(
                Subcontractor.company_id == company_id,
                Subcontractor.is_deleted.is_(False),
                sim(Subcontractor.name, vendor_name) >= PG_TRGM_THRESHOLD,
            )
        ).all():
            matched_sub_ids.add(sid)
            matched_names.add(name)

    return matched_suppliers, matched_sub_ids, sorted(matched_names)


def _resolve_vendor(db: Session, company_id, vendor_name: str) -> Vendor | None:
    """CR-008-G: resolve a free-text query to a canonical Vendor by exact
    normalised match against its aliases, then its canonical name. Returns None
    if no vendor matches (then the legacy pg_trgm/normalised fallback applies)."""
    norm = normalize_vendor_name(vendor_name)
    if not norm:
        return None
    alias = db.execute(
        select(VendorAlias).where(
            VendorAlias.company_id == company_id,
            VendorAlias.alias_normalised == norm,
            VendorAlias.is_deleted.is_(False),
        )
    ).scalars().first()
    if alias:
        v = db.get(Vendor, alias.vendor_id)
        if v is not None and not v.is_deleted:
            return v
    for v in db.execute(
        select(Vendor).where(Vendor.company_id == company_id, Vendor.is_deleted.is_(False))
    ).scalars().all():
        if normalize_vendor_name(v.canonical_name) == norm:
            return v
    return None


def get_vendor_spend(db: Session, company_id, *, vendor_name: str,
                     date_from: date | None = None, date_to: date | None = None) -> dict:
    """Cross-portfolio spend with one vendor, broken down by month, category and
    project, citing the underlying cost entries (§5.2). The headline tool.

    CR-008-G: prefers an exact ``vendor_id`` match (canonical vendor + aliases);
    unlinked legacy rows (vendor_id IS NULL) still match via the CR-007
    normalised/pg_trgm fallback so nothing regresses."""
    vendor = _resolve_vendor(db, company_id, vendor_name)
    suppliers, sub_ids, legacy_names = _matching_vendors(db, company_id, vendor_name)

    match_or = []
    matched_names: set[str] = set()

    if vendor is not None:
        # Primary, exact path: rows linked to this canonical vendor.
        match_or.append(CostEntry.vendor_id == vendor.id)
        aliases = db.execute(
            select(VendorAlias.alias_name).where(
                VendorAlias.vendor_id == vendor.id, VendorAlias.is_deleted.is_(False)
            )
        ).scalars().all()
        matched_names.add(vendor.canonical_name)
        matched_names.update(aliases)

    # Legacy fallback for still-unlinked rows. When a vendor resolved, only
    # vendor_id IS NULL rows fall back (linked rows already counted, no double).
    legacy_or = []
    if suppliers:
        legacy_or.append(CostEntry.supplier_name.in_(suppliers))
    if sub_ids:
        legacy_or.append(CostEntry.subcontractor_id.in_(sub_ids))
    if legacy_or:
        if vendor is not None:
            match_or.append(and_(CostEntry.vendor_id.is_(None), or_(*legacy_or)))
        else:
            match_or.append(or_(*legacy_or))
            matched_names.update(legacy_names)

    if not match_or:
        return {
            "summary": {
                "vendor_name": vendor.canonical_name if vendor else vendor_name,
                "matched_names": sorted(matched_names),
                "total_try": "0.00", "total_with_vat_try": "0.00",
                "invoice_count": 0, "project_count": 0,
                "by_month": [], "by_category": [], "by_project": [],
            },
            "records": [], "row_count": 0, "truncated": False,
        }

    conds = [
        CostEntry.company_id == company_id,
        CostEntry.is_deleted.is_(False),
        CostEntry.pending_approval.is_(False),
        or_(*match_or),
    ]
    if date_from is not None:
        conds.append(CostEntry.entry_date >= date_from)
    if date_to is not None:
        conds.append(CostEntry.entry_date <= date_to)

    totals = db.execute(
        select(
            func.coalesce(func.sum(CostEntry.amount_try), 0),
            func.coalesce(func.sum(CostEntry.total_with_vat_try), 0),
            func.count(CostEntry.id),
            func.count(func.distinct(CostEntry.project_id)),
        ).where(*conds)
    ).one()

    mb = month_bucket(db, CostEntry.entry_date)
    by_month = [
        {"month": _month_key(r[0]), "total": _s(r[1])}
        for r in db.execute(
            select(mb, func.coalesce(func.sum(CostEntry.amount_try), 0))
            .where(*conds).group_by(mb).order_by(mb)
        ).all()
    ]
    by_category = [
        {"category": r[0], "category_label": COST_CATEGORIES.get(r[0], r[0]), "total": _s(r[1])}
        for r in db.execute(
            select(CostEntry.cost_category, func.coalesce(func.sum(CostEntry.amount_try), 0))
            .where(*conds).group_by(CostEntry.cost_category).order_by(CostEntry.cost_category)
        ).all()
    ]
    projects = _company_projects(db, company_id)
    by_project = [
        {
            "project_id": str(r[0]),
            "project_name": projects[r[0]].name if r[0] in projects else str(r[0]),
            "total": _s(r[1]),
        }
        for r in db.execute(
            select(CostEntry.project_id, func.coalesce(func.sum(CostEntry.amount_try), 0))
            .where(*conds).group_by(CostEntry.project_id)
        ).all()
    ]

    rows = db.execute(
        select(CostEntry).where(*conds).order_by(CostEntry.entry_date.desc()).limit(MAX_RECORDS + 1)
    ).scalars().all()
    truncated = len(rows) > MAX_RECORDS
    sub_names = {sid: nm for sid, nm in db.execute(
        select(Subcontractor.id, Subcontractor.name).where(Subcontractor.id.in_(sub_ids))
    ).all()} if sub_ids else {}
    records = [{
        "id": str(c.id),
        "project_id": str(c.project_id),
        "project_name": projects[c.project_id].name if c.project_id in projects else None,
        "supplier_name": c.supplier_name or sub_names.get(c.subcontractor_id),
        "cost_category": c.cost_category,
        "amount_try": _s(c.amount_try),
        "total_with_vat_try": _s(c.total_with_vat_try),
        "entry_date": c.entry_date.isoformat() if c.entry_date else None,
        "payment_status": c.payment_status,
        "deep_link": _deep_link("cost_entry", c.project_id, c.id),
    } for c in rows[:MAX_RECORDS]]

    return {
        "summary": {
            "vendor_name": vendor.canonical_name if vendor else vendor_name,
            "matched_names": sorted(matched_names),
            "total_try": _s(totals[0]),
            "total_with_vat_try": _s(totals[1]),
            "invoice_count": int(totals[2]),
            "project_count": int(totals[3]),
            "by_month": by_month,
            "by_category": by_category,
            "by_project": by_project,
        },
        "records": records,
        "row_count": len(records),
        "truncated": truncated,
    }


def compare_vendors(db: Session, company_id, *, date_from: date | None = None,
                    date_to: date | None = None, top_n: int = 5,
                    cost_category: str | None = None) -> dict:
    """Total spend per vendor over a window, ranked desc, limited to top_n (§5.3).

    CR-008-G: groups by the canonical vendor name when a row is linked
    (``vendor_id``), else falls back to COALESCE(supplier_name, subcontractor.name)
    for unlinked legacy rows. Raw names that normalise to the same vendor are then
    merged (summing SQL-computed subtotals — the get_cashflow per-project pattern)."""
    vendor_expr = func.coalesce(
        Vendor.canonical_name, func.coalesce(CostEntry.supplier_name, Subcontractor.name)
    )
    conds = [
        CostEntry.company_id == company_id,
        CostEntry.is_deleted.is_(False),
        CostEntry.pending_approval.is_(False),
        vendor_expr.is_not(None),
    ]
    if date_from is not None:
        conds.append(CostEntry.entry_date >= date_from)
    if date_to is not None:
        conds.append(CostEntry.entry_date <= date_to)
    if cost_category:
        conds.append(CostEntry.cost_category == cost_category)

    rows = db.execute(
        select(
            vendor_expr,
            func.coalesce(func.sum(CostEntry.amount_try), 0),
            func.count(CostEntry.id),
        )
        .select_from(CostEntry)
        .join(Subcontractor, CostEntry.subcontractor_id == Subcontractor.id, isouter=True)
        .join(Vendor, CostEntry.vendor_id == Vendor.id, isouter=True)
        .where(*conds)
        .group_by(vendor_expr)
    ).all()

    # Merge raw names that normalise to the same vendor.
    merged: dict[str, dict] = {}
    for name, total, count in rows:
        key = normalize_vendor_name(name)
        if not key:
            continue
        agg = merged.setdefault(key, {"vendor_name": name, "total": D(0), "count": 0})
        agg["total"] += D(total)
        agg["count"] += int(count)
        # Prefer the longest raw spelling as the display name.
        if len(name) > len(agg["vendor_name"]):
            agg["vendor_name"] = name

    ranking = sorted(merged.values(), key=lambda a: a["total"], reverse=True)
    top = ranking[:top_n]
    return {
        "summary": {
            "ranking": [
                {"vendor_name": a["vendor_name"], "total_try": _s(a["total"]), "invoice_count": a["count"]}
                for a in top
            ],
            "vendor_count": len(merged),
            "top_n": top_n,
        },
        "records": [],
        "row_count": len(top),
        "truncated": len(merged) > top_n,
    }


# --------------------------------------------------------------------------- #
# CR-011-B — new read-only tools (equipment, budget variance, retention,
# assurance findings). Same contract: company-scoped, SQL-aggregated, returns
# {summary, records, row_count, truncated}; records carry deep_links for
# citation. The model still only narrates (§1.2).
# --------------------------------------------------------------------------- #
def get_equipment_utilisation(db: Session, company_id, *, project_id=None,
                              ownership_type: str | None = None, today: date | None = None) -> dict:
    """Equipment deployment & cost: per-machine deployment span, active/ended
    status, estimated rental (rate × span for rented) + fuel/maintenance, with
    portfolio totals by ownership. No work-hour log exists, so this reports
    deployment/cost (not a fabricated idle %)."""
    today = today or date.today()
    conds = [EquipmentLog.company_id == company_id, EquipmentLog.is_deleted.is_(False)]
    if project_id is not None:
        conds.append(EquipmentLog.project_id == project_id)
    if ownership_type in ("owned", "rented"):
        conds.append(EquipmentLog.ownership_type == ownership_type)

    rows = db.execute(
        select(EquipmentLog).where(*conds)
        .order_by(EquipmentLog.deployment_start.desc()).limit(MAX_RECORDS + 1)
    ).scalars().all()
    truncated = len(rows) > MAX_RECORDS
    rows = rows[:MAX_RECORDS]

    projects = _company_projects(db, company_id)
    records: list[dict] = []
    active_count = 0
    tot_est = D(0)
    tot_fuel = D(0)
    by_owner: dict[str, dict] = {}
    for e in rows:
        is_active = e.deployment_end is None or e.deployment_end >= today
        eff_end = e.deployment_end if (e.deployment_end is not None and e.deployment_end < today) else today
        days = max((eff_end - e.deployment_start).days + 1, 0) if e.deployment_start else 0
        rate = D(e.rate_try) if e.rate_try is not None else D(0)
        # Only rented equipment accrues a rental rate; owned est rental = 0.
        if e.ownership_type == "rented" and e.rate_unit == "day":
            est = money(rate * D(days))
        elif e.ownership_type == "rented" and e.rate_unit == "month":
            est = money(rate * D(days) / D(30))
        else:
            est = D("0.00")
        fuel = money(e.fuel_maintenance_try or 0)
        total = money(D(est) + D(fuel))
        if is_active:
            active_count += 1
        tot_est += D(est)
        tot_fuel += D(fuel)
        ob = by_owner.setdefault(e.ownership_type, {"count": 0, "est": D(0), "fuel": D(0)})
        ob["count"] += 1
        ob["est"] += D(est)
        ob["fuel"] += D(fuel)
        records.append({
            "id": str(e.id),
            "project_id": str(e.project_id),
            "project_name": projects[e.project_id].name if e.project_id in projects else None,
            "name": e.equipment_name,
            "ownership_type": e.ownership_type,
            "supplier_name": e.supplier_name,
            "deployment_start": e.deployment_start.isoformat() if e.deployment_start else None,
            "deployment_end": e.deployment_end.isoformat() if e.deployment_end else None,
            "is_active": is_active,
            "deployment_days": days,
            "rate_try": _s(rate),
            "rate_unit": e.rate_unit,
            "estimated_rental_try": _s(est),
            "fuel_maintenance_try": _s(fuel),
            "total_cost_try": _s(total),
            "deep_link": _deep_link("equipment", e.project_id, e.id),
        })

    return {
        "summary": {
            "equipment_count": len(records),
            "active_count": active_count,
            "ended_count": len(records) - active_count,
            "total_estimated_rental_try": _s(tot_est),
            "total_fuel_maintenance_try": _s(tot_fuel),
            "total_cost_try": _s(D(tot_est) + D(tot_fuel)),
            "by_ownership": {
                k: {"count": v["count"], "estimated_rental_try": _s(v["est"]),
                    "fuel_maintenance_try": _s(v["fuel"])}
                for k, v in by_owner.items()
            },
        },
        "records": records,
        "row_count": len(records),
        "truncated": truncated,
    }


def get_budget_variance(db: Session, company_id, *, project_id=None,
                        cost_category: str | None = None) -> dict:
    """Budget-vs-actual variance per project/category. Revised budget =
    original_budget + approved_variations (budget_line_items); actual = VAT-
    inclusive 'actual' cost entries (matching the dashboard's over-budget rule).
    Variance = revised − actual (positive = under budget). Both sides summed in
    SQL, then joined by (project, category)."""
    bconds = [BudgetLineItem.company_id == company_id, BudgetLineItem.is_deleted.is_(False)]
    aconds = [
        CostEntry.company_id == company_id, CostEntry.is_deleted.is_(False),
        CostEntry.pending_approval.is_(False), CostEntry.entry_type == "actual",
    ]
    if project_id is not None:
        bconds.append(BudgetLineItem.project_id == project_id)
        aconds.append(CostEntry.project_id == project_id)
    if cost_category:
        bconds.append(BudgetLineItem.cost_category == cost_category)
        aconds.append(CostEntry.cost_category == cost_category)

    budget_rows = db.execute(
        select(
            BudgetLineItem.project_id, BudgetLineItem.cost_category,
            func.coalesce(func.sum(BudgetLineItem.original_budget_try), 0),
            func.coalesce(func.sum(BudgetLineItem.approved_variations_try), 0),
        ).where(*bconds).group_by(BudgetLineItem.project_id, BudgetLineItem.cost_category)
    ).all()
    actual_rows = db.execute(
        select(
            CostEntry.project_id, CostEntry.cost_category,
            func.coalesce(func.sum(CostEntry.total_with_vat_try), 0),
        ).where(*aconds).group_by(CostEntry.project_id, CostEntry.cost_category)
    ).all()

    merged: dict[tuple, dict] = {}
    for pid, cat, orig, var in budget_rows:
        m = merged.setdefault((pid, cat), {"budget": D(0), "actual": D(0)})
        m["budget"] += D(orig) + D(var)
    for pid, cat, act in actual_rows:
        m = merged.setdefault((pid, cat), {"budget": D(0), "actual": D(0)})
        m["actual"] += D(act)

    projects = _company_projects(db, company_id)
    records: list[dict] = []
    tot_budget = D(0)
    tot_actual = D(0)
    over_count = 0
    for (pid, cat), m in merged.items():
        budget = money(m["budget"])
        actual = money(m["actual"])
        variance = money(D(budget) - D(actual))
        over = D(actual) > D(budget)
        if over:
            over_count += 1
        tot_budget += D(budget)
        tot_actual += D(actual)
        records.append({
            "id": f"{pid}:{cat}",
            "project_id": str(pid),
            "project_name": projects[pid].name if pid in projects else None,
            "cost_category": cat,
            "cost_category_label": COST_CATEGORIES.get(cat, cat),
            "revised_budget_try": _s(budget),
            "actual_try": _s(actual),
            "variance_try": _s(variance),
            "variance_pct": _s((D(variance) / D(budget) * D(100)) if D(budget) > 0 else D(0)),
            "over_budget": over,
            # Category aggregate -> project deep_link (no single record to highlight).
            "deep_link": _deep_link("project", pid, pid),
        })

    # Most over-budget (most negative variance) first.
    records.sort(key=lambda r: D(r["variance_try"]))
    return {
        "summary": {
            "category_count": len(records),
            "total_revised_budget_try": _s(tot_budget),
            "total_actual_try": _s(tot_actual),
            "total_variance_try": _s(D(tot_budget) - D(tot_actual)),
            "over_budget_category_count": over_count,
            "over_budget": D(tot_actual) > D(tot_budget),
        },
        "records": records[:MAX_RECORDS],
        "row_count": len(records),
        "truncated": len(records) > MAX_RECORDS,
    }


def get_retention_summary(db: Session, company_id, *, project_id=None) -> dict:
    """Teminat/retention held on hakediş (client invoices): outstanding retained
    amounts, totalled in SQL and broken down per project, plus the underlying
    invoices (cited). 'Outstanding' = retained amount held by the client (no
    release ledger exists, so the held amount is the outstanding retention)."""
    conds = [
        ClientInvoice.company_id == company_id,
        ClientInvoice.is_deleted.is_(False),
        ClientInvoice.retention_amount_try > 0,
    ]
    if project_id is not None:
        conds.append(ClientInvoice.project_id == project_id)

    totals = db.execute(
        select(
            func.coalesce(func.sum(ClientInvoice.retention_amount_try), 0),
            func.count(ClientInvoice.id),
            func.count(func.distinct(ClientInvoice.project_id)),
        ).where(*conds)
    ).one()
    by_project_rows = db.execute(
        select(
            ClientInvoice.project_id,
            func.coalesce(func.sum(ClientInvoice.retention_amount_try), 0),
            func.count(ClientInvoice.id),
        ).where(*conds).group_by(ClientInvoice.project_id)
    ).all()
    projects = _company_projects(db, company_id)
    by_project = [{
        "project_id": str(r[0]),
        "project_name": projects[r[0]].name if r[0] in projects else str(r[0]),
        "retention_held_try": _s(r[1]),
        "invoice_count": int(r[2]),
    } for r in by_project_rows]

    rows = db.execute(
        select(ClientInvoice).where(*conds)
        .order_by(ClientInvoice.retention_amount_try.desc()).limit(MAX_RECORDS + 1)
    ).scalars().all()
    truncated = len(rows) > MAX_RECORDS
    records = [{
        "id": str(i.id),
        "project_id": str(i.project_id),
        "invoice_number": i.invoice_number,
        "invoice_date": i.invoice_date.isoformat() if i.invoice_date else None,
        "retention_amount_try": _s(i.retention_amount_try),
        "total_with_vat_try": _s(i.total_with_vat_try),
        "net_due_try": _s(i.net_due_try),
        "payment_status": i.payment_status,
        "deep_link": _deep_link("client_invoice", i.project_id, i.id),
    } for i in rows[:MAX_RECORDS]]

    return {
        "summary": {
            "total_retention_held_try": _s(totals[0]),
            "invoice_count": int(totals[1]),
            "project_count": int(totals[2]),
            "by_project": by_project,
        },
        "records": records,
        "row_count": len(records),
        "truncated": truncated,
    }


def get_assurance_findings(db: Session, company_id, *, project_id=None,
                           severity: str | None = None) -> dict:
    """Open CR-022 Finans Güvence (assurance) findings — anomaly AIAlerts
    (dedup_key set) that are not actively dismissed — so the agent can answer
    'hangi faturaları/maliyetleri incelemeliyim?' with deep-links to the flagged
    source record."""
    now = datetime.now(timezone.utc)
    conds = [AIAlert.company_id == company_id, AIAlert.dedup_key.is_not(None)]
    if project_id is not None:
        conds.append(AIAlert.project_id == project_id)
    if severity in ("high", "medium", "low"):
        conds.append(AIAlert.severity == severity)

    rows = db.execute(
        select(AIAlert).where(*conds).order_by(AIAlert.created_at.desc())
    ).scalars().all()
    projects = _company_projects(db, company_id)
    records: list[dict] = []
    by_sev: dict[str, int] = {}
    for a in rows:
        # Open = not dismissed, or the 7-day dismissal window has elapsed
        # (mirrors GET /ai/alerts). Normalise naive timestamps (SQLite) to UTC so
        # the comparison is valid on both dialects.
        du = a.dismissed_until
        if du is not None and du.tzinfo is None:
            du = du.replace(tzinfo=timezone.utc)
        if a.is_dismissed and (du is None or du > now):
            continue
        by_sev[a.severity] = by_sev.get(a.severity, 0) + 1
        link = ""
        if a.source_type and a.source_id and a.project_id:
            link = _deep_link(a.source_type, a.project_id, a.source_id)
        elif a.project_id:
            link = _deep_link("project", a.project_id, a.project_id)
        records.append({
            "id": str(a.id),
            "project_id": str(a.project_id) if a.project_id else None,
            "project_name": projects[a.project_id].name if a.project_id in projects else None,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "title": a.title_tr,
            "body": a.body_tr,
            "recommended_action": a.recommended_action,
            "source_type": a.source_type,
            "source_id": str(a.source_id) if a.source_id else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "deep_link": link,
        })

    return {
        "summary": {
            "finding_count": len(records),
            "by_severity": by_sev,
        },
        "records": records[:MAX_RECORDS],
        "row_count": len(records),
        "truncated": len(records) > MAX_RECORDS,
    }
