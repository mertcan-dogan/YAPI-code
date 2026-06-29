"""CR-032 §4 — the read-only query engine.

``run_spec(db, company_id, spec)`` turns a validated spec (§2) into the result
shape (§2). It REUSES the existing financial services and never reinvents money
math:

* cost-line metrics — a Python group+sum over ``cost_entries`` rows, with CR-023
  open-commitment via ``relief_by_commitment`` / ``open_commitment`` (materializing
  rows also makes time-bucketing dialect-proof).
* project metrics — ``financials.project_financials`` / ``forecast_at_completion``
  and ``sales.project_pnl`` (revenue is revenue-model-aware → never double-counted).
* cash metrics — ``financials.project_cashflow`` / ``project_cashflow_window``.
* unit metrics — ``sales.unit_sales_pnl`` allocations grouped by ``unit_type``.

Invariants (§4.8): every query is filtered by ``company_id`` (defense-in-depth on
top of RLS); ``company_id`` is the function argument from the authenticated user
and is NEVER read from the spec/body. The engine issues SELECTs only — no
add/flush/commit, no ORM attribute writes — so running any spec mutates nothing.

Note (v1 scope): project-grain and unit-grain figures are whole-project snapshots
(the underlying services aren't windowed), so ``date_range``/``comparison`` scope
cost-line and cash metrics; project/unit metrics are window-independent.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.calculations.money import D, safe_div
from app.calculations.project_financials import open_commitment, relief_by_commitment
from app.constants import COST_CATEGORIES, UNIT_TYPES
from app.models.cost_entry import CostEntry
from app.models.project import Project
from app.models.subcontractor import Subcontractor
from app.models.vendor import Vendor
from app.services import financials as fin_service
from app.services import sales as sales_service
from app.services.studio.catalog import (
    DIMENSIONS,
    GRAIN_CASH,
    GRAIN_COST_LINE,
    GRAIN_PROJECT,
    GRAIN_UNIT,
    HARD_ROW_LIMIT,
    METRICS,
    STATUS_AVAILABLE,
    validate_spec,
)

ZERO = Decimal("0")
HUNDRED = Decimal("100")
NONE_KEY = "__none__"
NONE_LABEL = "(belirtilmemiş)"


# --------------------------------------------------------------------------- #
# Date presets (§3.3 "accept both") — English aliases → the live Turkish
# resolver presets (``services.agent.resolve_window``). ``previous_period`` is NOT
# a resolver preset — it is computed in-engine as the preceding equal-length window.
# --------------------------------------------------------------------------- #
_PRESET_ALIASES = {
    "this_month": "bu_ay", "current_month": "bu_ay",
    "last_month": "gecen_ay", "previous_month": "gecen_ay",
    "last_3_months": "son_3_ay", "last_quarter_rolling": "son_3_ay",
    "last_6_months": "son_6_ay",
    "last_12_months": "son_12_ay", "ttm": "son_12_ay", "trailing_12_months": "son_12_ay",
    "ytd": "bu_yil", "this_year": "bu_yil", "year_to_date": "bu_yil",
    "last_year": "gecen_yil", "previous_year": "gecen_yil",
    "this_quarter": "bu_ceyrek", "current_quarter": "bu_ceyrek",
    "last_quarter": "gecen_ceyrek", "previous_quarter": "gecen_ceyrek",
}
_PREVIOUS_PERIOD = "previous_period"


def _turkish_preset(name: str) -> str | None:
    """Map a spec preset (English alias or Turkish) → the resolver's Turkish name,
    or None if unknown."""
    from app.services.agent import RELATIVE_WINDOWS

    if name in RELATIVE_WINDOWS:
        return name
    return _PRESET_ALIASES.get(name)


def is_known_preset(name) -> bool:
    """True for any preset the engine can resolve (English alias, Turkish, or the
    in-engine ``previous_period``). Used by ``catalog.validate_spec``."""
    return name == _PREVIOUS_PERIOD or _turkish_preset(str(name)) is not None


def _resolve_window(window, today: date) -> tuple[date | None, date | None]:
    """Resolve a date_range spec to literal (from, to). Missing → (None, None) =
    all-time (no date filter)."""
    if not window:
        return None, None
    if "preset" in window:
        from app.services.agent import resolve_window as agent_resolve

        tr = _turkish_preset(window["preset"])
        if tr is None:  # validated upstream, but never raise here
            return None, None
        return agent_resolve(tr, today)
    if "from" in window or "to" in window:
        d_from = date.fromisoformat(window["from"]) if window.get("from") else None
        d_to = date.fromisoformat(window["to"]) if window.get("to") else None
        return d_from, d_to
    return None, None


def _resolve_comparison(comparison, date_from, date_to, today) -> tuple[date | None, date | None]:
    if not comparison:
        return None, None
    if comparison.get("preset") == _PREVIOUS_PERIOD:
        if date_from is None or date_to is None:
            return None, None  # can't derive a prior period without an explicit window
        length = (date_to - date_from).days
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=length)
        return prev_from, prev_to
    return _resolve_window(comparison, today)


# --------------------------------------------------------------------------- #
# Spec helpers
# --------------------------------------------------------------------------- #
def _normalize_basis(b) -> dict:
    b = b or {}

    def pick(key, allowed, default):
        v = b.get(key, default)
        return v if v in allowed else default

    return {
        "cost": pick("cost", ("actual", "actual_plus_open"), "actual"),
        "currency": pick("currency", ("try", "usd"), "try"),
        "financing": pick("financing", ("excl", "incl"), "excl"),
        "vat": pick("vat", ("excl", "incl"), "excl"),
    }


def _match(op: str, value, target) -> bool:
    """Apply a filter operator. ``=`` is lenient (matches a scalar or membership)."""
    if op == "=":
        return target == value or (isinstance(value, list) and target in value)
    if op == "!=":
        return target != value
    if op == "in":
        return target in (value if isinstance(value, list) else [value])
    if op == "not_in":
        return target not in (value if isinstance(value, list) else [value])
    return True


def _split_filters(filters) -> tuple[list, list]:
    """Project-level filters (project/revenue_model/project_status) vs cost-row
    filters (everything else)."""
    project_level, cost_level = [], []
    for f in filters or []:
        bucket = project_level if f["field"] in ("project", "revenue_model", "project_status") else cost_level
        bucket.append((f["field"], f["op"], f["value"]))
    return project_level, cost_level


def _effective_grain(mid: str, dims: list) -> str:
    m = METRICS[mid]
    if m["dual"] and "unit_type" in dims:
        return GRAIN_UNIT
    return m["grain"]


def _dims_supported(dims: list, grain: str) -> bool:
    return all(grain in DIMENSIONS[d]["grains"] for d in dims)


def _bucket(d: date, grain: str) -> str:
    if grain == "year":
        return f"{d.year:04d}"
    if grain == "quarter":
        return f"{d.year:04d}-Q{(d.month - 1) // 3 + 1}"
    if grain == "week":
        iso = d.isocalendar()
        return f"{iso[0]:04d}-W{iso[1]:02d}"
    return f"{d.year:04d}-{d.month:02d}"  # month


def _num(x):
    return None if x is None else round(float(x), 2)


# --------------------------------------------------------------------------- #
# Per-request context (company-scoped; caches the window-independent bundles)
# --------------------------------------------------------------------------- #
class _Ctx:
    def __init__(self, db, company_id, projects, basis, cost_filters, today):
        self.db = db
        self.company_id = company_id
        self.projects = projects
        self.basis = basis
        self.cost_filters = cost_filters
        self.today = today
        self.project_by_id = {p.id: p for p in projects}
        self.project_ids = [p.id for p in projects]
        # Set (not a counter) so re-running the cost resolver across the primary +
        # totals + comparison passes counts each missing-snapshot row once.
        self._usd_missing_ids: set = set()
        self._cost_cache: dict = {}
        self._bundle_cache: dict = {}
        self._unit_cache: dict = {}
        self._cash_cache: dict = {}
        self._irr_cache: dict = {}
        self._vendor_names: dict | None = None
        self._subcon_names: dict | None = None

    @property
    def usd_missing_count(self) -> int:
        return len(self._usd_missing_ids)

    # --- cost rows (window-filtered, company-scoped; NOT spec-filtered so relief
    # stays consistent over the whole window) ---
    def cost_rows(self, date_from, date_to) -> list[dict]:
        key = (date_from, date_to)
        if key not in self._cost_cache:
            self._cost_cache[key] = self._load_cost_rows(date_from, date_to)
        return self._cost_cache[key]

    def _load_cost_rows(self, date_from, date_to) -> list[dict]:
        if not self.project_ids:
            return []
        stmt = select(CostEntry).where(
            CostEntry.company_id == self.company_id,  # defense-in-depth on top of RLS
            CostEntry.project_id.in_(self.project_ids),
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),  # mirror query_cost_entries / dashboard
        )
        if date_from is not None:
            stmt = stmt.where(CostEntry.entry_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(CostEntry.entry_date <= date_to)
        rows = []
        for c in self.db.execute(stmt).scalars().all():
            rows.append({
                "id": c.id, "commitment_id": c.commitment_id, "project_id": c.project_id,
                "amount_try": c.amount_try, "total_with_vat_try": c.total_with_vat_try,
                "amount_usd": c.amount_usd, "entry_type": c.entry_type or "actual",
                "payment_status": c.payment_status or "unpaid", "cost_category": c.cost_category,
                "subcategory": c.subcategory, "vendor_id": c.vendor_id,
                "supplier_name": c.supplier_name, "subcontractor_id": c.subcontractor_id,
                "entry_date": c.entry_date,
            })
        return rows

    def project_bundle(self, project) -> dict:
        if project.id not in self._bundle_cache:
            self._bundle_cache[project.id] = _build_bundle(self.db, project, self.today)
        return self._bundle_cache[project.id]

    def unit_allocations(self, project) -> list[dict]:
        if project.id not in self._unit_cache:
            res = sales_service.unit_sales_pnl(self.db, project, today=self.today)
            self._unit_cache[project.id] = res.get("allocations", [])
        return self._unit_cache[project.id]

    def project_irr(self, project) -> Decimal | None:
        if project.id not in self._irr_cache:
            inv = sales_service.investment_return(self.db, project, today=self.today)
            cur = self.basis["currency"]
            raw = inv.get("irr_usd_pct") if cur == "usd" else inv.get("irr_try_pct")
            self._irr_cache[project.id] = D(raw) if raw is not None else None
        return self._irr_cache[project.id]

    def cashflow_rows(self, project, from_month, to_month) -> list[dict]:
        key = (project.id, from_month, to_month)
        if key not in self._cash_cache:
            if from_month and to_month:
                res = fin_service.project_cashflow_window(
                    self.db, project, from_month=from_month, to_month=to_month, today=self.today
                )
                self._cash_cache[key] = res["rows"]
            else:
                self._cash_cache[key] = fin_service.project_cashflow(self.db, project, today=self.today)
        return self._cash_cache[key]

    @property
    def vendor_names(self) -> dict:
        if self._vendor_names is None:
            rows = self.db.execute(
                select(Vendor.id, Vendor.canonical_name).where(
                    Vendor.company_id == self.company_id, Vendor.is_deleted.is_(False)
                )
            ).all()
            self._vendor_names = {vid: name for vid, name in rows}
        return self._vendor_names

    @property
    def subcontractor_names(self) -> dict:
        if self._subcon_names is None:
            rows = self.db.execute(
                select(Subcontractor.id, Subcontractor.name).where(
                    Subcontractor.company_id == self.company_id, Subcontractor.is_deleted.is_(False)
                )
            ).all()
            self._subcon_names = {sid: name for sid, name in rows}
        return self._subcon_names


def _build_bundle(db, project, today) -> dict:
    """Per-project component bundle — the additive pieces every project-grain
    metric is derived from. Reuses the authoritative services; revenue routes
    through project_pnl so it is revenue-model-aware (never double-counted)."""
    pf = fin_service.project_financials(db, project, today=today)
    fac = fin_service.forecast_at_completion(db, project)
    pnl = sales_service.project_pnl(db, project, today=today)
    bd = pnl.get("revenue_breakdown", {})
    return {
        "revenue_try": D(pnl["revenue_try"]), "revenue_usd": D(pnl["revenue_usd"]),
        "pnl_cost_try": D(pnl["cost_try"]), "pnl_cost_usd": D(pnl["cost_usd"]),
        "net_excl_try": D(pnl["net_excl_financing_try"]), "net_excl_usd": D(pnl["net_excl_financing_usd"]),
        "net_incl_try": D(pnl["net_incl_financing_try"]), "net_incl_usd": D(pnl["net_incl_financing_usd"]),
        "unit_sales_try": D(bd.get("unit_sales_try", 0)), "unit_sales_usd": D(bd.get("unit_sales_usd", 0)),
        "forecast_final_try": D(fac["forecast_final_cost_try"]),
        "forecast_final_fin_try": D(fac["forecast_final_cost_with_financing_try"]),
        "revised_budget_try": D(fac["revised_budget_try"]),
        "invoiced_try": D(pf["total_invoiced_try"]),
        "outstanding_try": D(pf["total_outstanding_try"]),
        "contract_try": D(project.contract_value_try),
        "net_m2": D(project.construction_net_m2) if project.construction_net_m2 is not None else ZERO,
    }


# --------------------------------------------------------------------------- #
# Cost-line resolver
# --------------------------------------------------------------------------- #
def _cost_amount_key(mid: str, basis: dict) -> str:
    if mid == "cost_usd":
        return "amount_usd"
    if mid == "cost_try":
        return "total_with_vat_try" if basis["vat"] == "incl" else "amount_try"
    # committed / open_commitment / exposure follow the currency + vat toggles.
    if basis["currency"] == "usd":
        return "amount_usd"
    return "total_with_vat_try" if basis["vat"] == "incl" else "amount_try"


def _cost_measure(row: dict, mid: str, basis: dict, relief: dict, amount_key: str) -> Decimal:
    etype = row["entry_type"]
    amt = D(row.get(amount_key))
    if mid in ("cost_try", "cost_usd"):
        if basis["cost"] == "actual_plus_open":
            if etype == "actual":
                return amt
            if etype == "committed":
                return open_commitment(row, relief, amount_key)
            return ZERO
        return amt if etype == "actual" else ZERO
    if mid == "committed":
        return amt if etype == "committed" else ZERO
    if mid == "open_commitment":
        return open_commitment(row, relief, amount_key) if etype == "committed" else ZERO
    if mid == "exposure":  # actual + open commitment (definition; ignores cost toggle)
        if etype == "actual":
            return amt
        if etype == "committed":
            return open_commitment(row, relief, amount_key)
        return ZERO
    return ZERO


def _vendor_dimval(row, ctx):
    vid = row.get("vendor_id")
    if vid is not None:
        return str(vid), ctx.vendor_names.get(vid, row.get("supplier_name") or NONE_LABEL)
    supplier = row.get("supplier_name")
    if supplier:
        return f"s:{supplier}", supplier
    return NONE_KEY, NONE_LABEL


def _cost_dimvals(row, dims, ctx) -> dict:
    p = ctx.project_by_id.get(row["project_id"])
    out = {}
    for d in dims:
        if d == "project":
            out[d] = (str(row["project_id"]), p.name if p else str(row["project_id"]))
        elif d == "revenue_model":
            v = p.revenue_model if p else None
            out[d] = (v or NONE_KEY, v or NONE_LABEL)
        elif d == "project_status":
            v = p.status if p else None
            out[d] = (v or NONE_KEY, v or NONE_LABEL)
        elif d == "cost_category":
            v = row["cost_category"]
            out[d] = (v or NONE_KEY, COST_CATEGORIES.get(v, v) if v else NONE_LABEL)
        elif d == "cost_subcategory":
            v = row["subcategory"]
            out[d] = (v or NONE_KEY, v or NONE_LABEL)
        elif d == "entry_type":
            v = row["entry_type"]
            out[d] = (v, v)
        elif d == "payment_status":
            v = row["payment_status"]
            out[d] = (v, v)
        elif d == "vendor":
            out[d] = _vendor_dimval(row, ctx)
        elif d == "subcontractor":
            sid = row.get("subcontractor_id")
            out[d] = (str(sid), ctx.subcontractor_names.get(sid, NONE_LABEL)) if sid else (NONE_KEY, NONE_LABEL)
        else:  # week / month / quarter / year
            k = _bucket(row["entry_date"], d)
            out[d] = (k, k)
    return out


def _cost_row_passes(row, ctx) -> bool:
    """Apply spec cost-row filters (relief is already computed over the full
    window, so a display filter can't corrupt open_commitment)."""
    for field, op, value in ctx.cost_filters:
        if field == "cost_category":
            target = row["cost_category"]
        elif field == "cost_subcategory":
            target = row["subcategory"]
        elif field == "entry_type":
            target = row["entry_type"]
        elif field == "payment_status":
            target = row["payment_status"]
        elif field == "vendor":
            target = str(row["vendor_id"]) if row.get("vendor_id") else None
        elif field == "subcontractor":
            target = str(row["subcontractor_id"]) if row.get("subcontractor_id") else None
        else:
            continue  # time/unit_type filters aren't applied to cost rows
        if not _match(op, value, target):
            return False
    return True


def _resolve_cost_groups(ctx, dims, metric_ids, date_from, date_to) -> dict:
    rows = ctx.cost_rows(date_from, date_to)
    # Relief per amount_key actually needed (CR-023, over the full window).
    relief_cache: dict = {}
    amount_keys = {mid: _cost_amount_key(mid, ctx.basis) for mid in metric_ids}
    for ak in set(amount_keys.values()):
        relief_cache[ak] = relief_by_commitment(rows, ak)
    usd_keys = {ak for ak in amount_keys.values() if ak == "amount_usd"}

    groups: dict = {}
    for row in rows:
        if not _cost_row_passes(row, ctx):
            continue
        if usd_keys and row.get("amount_usd") is None:
            ctx._usd_missing_ids.add(row["id"])
        dimvals = _cost_dimvals(row, dims, ctx)
        key = tuple(dimvals[d][0] for d in dims)
        slot = groups.get(key)
        if slot is None:
            slot = {"dims": {d: dimvals[d][1] for d in dims}, "metrics": {m: ZERO for m in metric_ids}}
            groups[key] = slot
        for mid in metric_ids:
            ak = amount_keys[mid]
            slot["metrics"][mid] += _cost_measure(row, mid, ctx.basis, relief_cache[ak], ak)
    return groups


# --------------------------------------------------------------------------- #
# Project resolver
# --------------------------------------------------------------------------- #
_ACC_KEYS = (
    "revenue_try", "revenue_usd", "pnl_cost_try", "pnl_cost_usd", "net_excl_try", "net_excl_usd",
    "net_incl_try", "net_incl_usd", "unit_sales_try", "unit_sales_usd", "forecast_final_try",
    "forecast_final_fin_try", "revised_budget_try", "invoiced_try", "outstanding_try",
    "contract_try", "net_m2",
)


def _project_dimvals(p, dims) -> dict:
    out = {}
    for d in dims:
        if d == "project":
            out[d] = (str(p.id), p.name)
        elif d == "revenue_model":
            out[d] = (p.revenue_model or NONE_KEY, p.revenue_model or NONE_LABEL)
        elif d == "project_status":
            out[d] = (p.status or NONE_KEY, p.status or NONE_LABEL)
    return out


def _project_metric_value(mid, acc, basis, n, single_irr):
    usd = basis["currency"] == "usd"
    rev = acc["revenue_usd"] if usd else acc["revenue_try"]
    cost = acc["pnl_cost_usd"] if usd else acc["pnl_cost_try"]
    net_excl = acc["net_excl_usd"] if usd else acc["net_excl_try"]
    net_incl = acc["net_incl_usd"] if usd else acc["net_incl_try"]
    m2 = acc["net_m2"]

    if mid == "budget":
        return None if usd else acc["revised_budget_try"]
    if mid == "forecast_final":
        return None if usd else acc["forecast_final_try"]
    if mid == "revenue":
        return rev
    if mid == "progress_billing":
        return None if usd else acc["invoiced_try"]
    if mid == "unit_sales_revenue":
        return acc["unit_sales_usd"] if usd else acc["unit_sales_try"]
    if mid == "receivables":
        return None if usd else acc["outstanding_try"]
    if mid == "gross_margin":
        return net_excl
    if mid == "pnl":
        return net_incl if basis["financing"] == "incl" else net_excl
    if mid == "net_profit_excl_fin":
        return net_excl
    if mid == "net_profit_incl_fin":
        return net_incl
    if mid == "margin_pct_current":
        rt = acc["revenue_try"]
        return safe_div(acc["net_excl_try"], rt) * HUNDRED if rt > ZERO else None
    if mid == "margin_pct_forecast":
        fc = acc["forecast_final_fin_try"] if basis["financing"] == "incl" else acc["forecast_final_try"]
        ct = acc["contract_try"]
        return safe_div(ct - fc, ct) * HUNDRED if ct > ZERO else None
    if mid == "billing_vs_contract":
        ct = acc["contract_try"]
        return safe_div(acc["invoiced_try"], ct) * HUNDRED if ct > ZERO else None
    if mid == "roi":
        return safe_div(acc["net_excl_try"], acc["pnl_cost_try"]) * HUNDRED if acc["pnl_cost_try"] > ZERO else None
    if mid == "cost_per_m2":
        return safe_div(cost, m2) if m2 > ZERO else None
    if mid == "revenue_per_m2":
        return safe_div(rev, m2) if m2 > ZERO else None
    if mid == "profit_per_m2":
        return safe_div(net_excl, m2) if m2 > ZERO else None
    if mid == "irr":
        return single_irr if n == 1 else None
    return None


def _resolve_project_groups(ctx, dims, metric_ids, date_from, date_to) -> dict:
    need_irr = "irr" in metric_ids
    acc_groups: dict = {}
    for p in ctx.projects:
        b = ctx.project_bundle(p)
        dimvals = _project_dimvals(p, dims)
        key = tuple(dimvals[d][0] for d in dims)
        g = acc_groups.get(key)
        if g is None:
            g = {"dims": {d: dimvals[d][1] for d in dims}, "acc": {k: ZERO for k in _ACC_KEYS},
                 "n": 0, "irr": None}
            acc_groups[key] = g
        for k in _ACC_KEYS:
            g["acc"][k] += b[k]
        g["n"] += 1
        if need_irr:
            g["irr"] = ctx.project_irr(p) if g["n"] == 1 else None

    out: dict = {}
    for key, g in acc_groups.items():
        metrics = {
            mid: _project_metric_value(mid, g["acc"], ctx.basis, g["n"], g["irr"])
            for mid in metric_ids
        }
        out[key] = {"dims": g["dims"], "metrics": metrics}
    return out


# --------------------------------------------------------------------------- #
# Cash resolver
# --------------------------------------------------------------------------- #
def _cash_dimvals(p, row, dims) -> dict:
    out = {}
    for d in dims:
        if d == "project":
            out[d] = (str(p.id), p.name)
        elif d == "year":
            out[d] = (f"{row['year']:04d}",) * 2
        elif d == "quarter":
            out[d] = ((f"{row['year']:04d}-Q{(row['month_num'] - 1) // 3 + 1}"),) * 2
        elif d == "month":
            out[d] = (row["month"], row["month"])
    return out


def _resolve_cash_groups(ctx, dims, metric_ids, date_from, date_to) -> dict:
    from_month = f"{date_from.year:04d}-{date_from.month:02d}" if date_from else None
    to_month = f"{date_to.year:04d}-{date_to.month:02d}" if date_to else None

    sums: dict = {}
    cum_track: dict = {}  # key -> {project_id: (month_key, cumulative)}
    labels: dict = {}
    for p in ctx.projects:
        for row in ctx.cashflow_rows(p, from_month, to_month):
            past = row["is_past"] or row["is_current"]
            eff_in = D(row["actual_in_try"]) if past else D(row["planned_in_try"])
            eff_out = D(row["actual_out_try"]) if past else D(row["planned_out_try"])
            dimvals = _cash_dimvals(p, row, dims)
            key = tuple(dimvals[d][0] for d in dims)
            if key not in sums:
                sums[key] = {"cash_in": ZERO, "cash_out": ZERO, "net_cash": ZERO}
                cum_track[key] = {}
                labels[key] = {d: dimvals[d][1] for d in dims}
            sums[key]["cash_in"] += eff_in
            sums[key]["cash_out"] += eff_out
            sums[key]["net_cash"] += D(row["net_try"])
            prev = cum_track[key].get(p.id)
            if prev is None or row["month"] >= prev[0]:
                cum_track[key][p.id] = (row["month"], D(row["cumulative_try"]))

    out: dict = {}
    for key, s in sums.items():
        cum = sum((v[1] for v in cum_track[key].values()), ZERO)
        full = {"cash_in": s["cash_in"], "cash_out": s["cash_out"], "net_cash": s["net_cash"], "cum_cash": cum}
        out[key] = {"dims": labels[key], "metrics": {m: full[m] for m in metric_ids}}
    return out


# --------------------------------------------------------------------------- #
# Unit resolver (unit_type grain — §3.3 flagship)
# --------------------------------------------------------------------------- #
def _unit_dimvals(p, alloc, dims) -> dict:
    out = {}
    for d in dims:
        if d == "project":
            out[d] = (str(p.id), p.name)
        elif d == "unit_type":
            ut = alloc.get("unit_type")
            out[d] = (ut or NONE_KEY, UNIT_TYPES.get(ut, ut) if ut else NONE_LABEL)
    return out


def _resolve_unit_groups(ctx, dims, metric_ids, date_from, date_to) -> dict:
    usd = ctx.basis["currency"] == "usd"
    acc: dict = {}
    for p in ctx.projects:
        for alloc in ctx.unit_allocations(p):
            dimvals = _unit_dimvals(p, alloc, dims)
            key = tuple(dimvals[d][0] for d in dims)
            g = acc.get(key)
            if g is None:
                g = {"dims": {d: dimvals[d][1] for d in dims},
                     "rev_try": ZERO, "rev_usd": ZERO, "pnl_try": ZERO, "pnl_usd": ZERO}
                acc[key] = g
            g["rev_try"] += D(alloc.get("sale_price_try"))
            g["rev_usd"] += D(alloc.get("sale_price_usd"))
            g["pnl_try"] += D(alloc.get("pnl_try"))
            g["pnl_usd"] += D(alloc.get("pnl_usd"))

    out: dict = {}
    for key, g in acc.items():
        rev = g["rev_usd"] if usd else g["rev_try"]
        pnl = g["pnl_usd"] if usd else g["pnl_try"]
        margin = safe_div(g["pnl_try"], g["rev_try"]) * HUNDRED if g["rev_try"] > ZERO else None
        full = {"unit_sales_revenue": rev, "pnl": pnl, "gross_margin": pnl, "margin_pct_current": margin}
        out[key] = {"dims": g["dims"], "metrics": {m: full.get(m) for m in metric_ids}}
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _load_projects(db, company_id, project_filters) -> list:
    projects = db.execute(
        select(Project).where(
            Project.company_id == company_id,  # defense-in-depth on top of RLS
            Project.is_deleted.is_(False),
        )
    ).scalars().all()
    if not project_filters:
        return list(projects)
    kept = []
    for p in projects:
        ok = True
        for field, op, value in project_filters:
            target = str(p.id) if field == "project" else getattr(p, field, None)
            if not _match(op, value, target):
                ok = False
                break
        if ok:
            kept.append(p)
    return kept


def _compute_groups(ctx, dims, metric_ids, date_from, date_to) -> dict:
    by_grain = {GRAIN_COST_LINE: [], GRAIN_PROJECT: [], GRAIN_CASH: [], GRAIN_UNIT: []}
    for mid in metric_ids:
        if METRICS[mid]["status"] != STATUS_AVAILABLE:
            continue  # coming_soon → null everywhere + meta.unavailable
        grain = _effective_grain(mid, dims)
        if not _dims_supported(dims, grain):
            continue  # grain/dimension mismatch → null cell (graceful, never raise)
        by_grain[grain].append(mid)

    groups: dict = {}

    def merge(partial):
        for key, g in partial.items():
            slot = groups.get(key)
            if slot is None:
                groups[key] = {"dims": dict(g["dims"]), "metrics": dict(g["metrics"])}
            else:
                slot["dims"].update(g["dims"])
                slot["metrics"].update(g["metrics"])

    if by_grain[GRAIN_COST_LINE]:
        merge(_resolve_cost_groups(ctx, dims, by_grain[GRAIN_COST_LINE], date_from, date_to))
    if by_grain[GRAIN_PROJECT]:
        merge(_resolve_project_groups(ctx, dims, by_grain[GRAIN_PROJECT], date_from, date_to))
    if by_grain[GRAIN_CASH]:
        merge(_resolve_cash_groups(ctx, dims, by_grain[GRAIN_CASH], date_from, date_to))
    if by_grain[GRAIN_UNIT]:
        merge(_resolve_unit_groups(ctx, dims, by_grain[GRAIN_UNIT], date_from, date_to))
    return groups


def _delta(sel, cmp, unit):
    if sel is None:
        return None
    if unit == "abs":
        base = cmp if cmp is not None else ZERO
        return _num(D(sel) - D(base))
    if cmp is None or D(cmp) == ZERO:
        return None
    return round(float((D(sel) - D(cmp)) / D(cmp)), 4)


def _window_meta(d_from, d_to) -> dict:
    return {"from": d_from.isoformat() if d_from else None, "to": d_to.isoformat() if d_to else None}


def _build_rows(primary, dims, metric_ids, compare, comparison_unit) -> list[dict]:
    rows = []
    for key, g in primary.items():
        metrics_out, deltas_out = {}, {}
        for mid in metric_ids:
            val = g["metrics"].get(mid)
            metrics_out[mid] = _num(val)
            if compare is not None:
                cval = compare.get(key, {}).get("metrics", {}).get(mid)
                deltas_out[mid] = _delta(val, cval, comparison_unit)
        rows.append({
            "dims": {d: g["dims"].get(d) for d in dims},
            "metrics": metrics_out,
            "deltas": deltas_out if compare is not None else None,
        })
    return rows


def _sort_rows(rows, sort, dims, metric_ids):
    if not rows:
        return rows
    by = sort["by"] if sort else (metric_ids[0] if metric_ids else None)
    if by is None:
        return rows
    descending = (sort.get("dir", "desc") if sort else "desc") == "desc"
    is_metric = by in metric_ids

    def keyfn(r):
        if is_metric:
            v = r["metrics"].get(by)
            return (v is None, v if v is not None else 0)
        v = r["dims"].get(by)
        return (v is None, str(v) if v is not None else "")

    rows.sort(key=keyfn, reverse=descending)
    return rows


def _build_columns(dims, metric_ids) -> list[dict]:
    cols = []
    for d in dims:
        md = DIMENSIONS[d]
        cols.append({"id": d, "label": md["label"], "kind": "dimension", "type": md["type"]})
    for mid in metric_ids:
        mm = METRICS[mid]
        cols.append({"id": mid, "label": mm["label"], "kind": "metric", "type": mm["type"]})
    return cols


def _series_x(dims, chart) -> str | None:
    x = chart.get("x")
    if x and x in dims:
        return x
    for d in dims:
        if DIMENSIONS[d]["type"] == "date":
            return d
    return dims[0] if dims else None


def _series_points(groups, x, metric) -> list[dict]:
    agg: dict = {}
    for g in groups.values():
        xlabel = g["dims"].get(x)
        if xlabel is None:
            continue
        val = g["metrics"].get(metric)
        if val is None:
            continue
        agg[xlabel] = agg.get(xlabel, ZERO) + D(val)
    return [{"x": xl, "y": _num(v)} for xl, v in sorted(agg.items(), key=lambda kv: str(kv[0]))]


def _build_series(primary, compare, dims, metric_ids, spec) -> list[dict]:
    chart = spec.get("chart")
    if not isinstance(chart, dict):  # validated upstream; coerce defensively, never raise
        chart = {}
    x = _series_x(dims, chart)
    if x is None:
        return []
    y_metrics = (chart.get("y_left") or []) + (chart.get("y_right") or [])
    y_metrics = [m for m in y_metrics if m in metric_ids] or list(metric_ids)
    series = []
    for m in y_metrics:
        entry = {"name": METRICS[m]["label"], "metric": m, "points": _series_points(primary, x, m)}
        entry["compare"] = _series_points(compare, x, m) if compare is not None else None
        series.append(entry)
    return series


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #
def run_spec(db, company_id, spec: dict, today: date | None = None) -> dict:
    """Validate + run a spec → the §2 result shape. Read-only; ``company_id`` is
    the caller's authenticated company and scopes every query."""
    validate_spec(spec)
    today = today or date.today()

    dims = list(spec.get("dimensions") or [])
    metric_ids = list(spec["metrics"])
    basis = _normalize_basis(spec.get("basis"))
    viz = spec.get("viz", "table")
    comparison_unit = spec.get("comparison_unit", "pct")

    project_filters, cost_filters = _split_filters(spec.get("filters"))
    date_from, date_to = _resolve_window(spec.get("date_range"), today)
    cmp_from, cmp_to = _resolve_comparison(spec.get("comparison"), date_from, date_to, today)

    projects = _load_projects(db, company_id, project_filters)
    ctx = _Ctx(db, company_id, projects, basis, cost_filters, today)

    unavailable = [m for m in metric_ids if METRICS[m]["status"] != STATUS_AVAILABLE]

    primary = _compute_groups(ctx, dims, metric_ids, date_from, date_to)
    totals = _compute_groups(ctx, [], metric_ids, date_from, date_to)
    compare = compare_totals = None
    if cmp_from is not None:
        compare = _compute_groups(ctx, dims, metric_ids, cmp_from, cmp_to)
        compare_totals = _compute_groups(ctx, [], metric_ids, cmp_from, cmp_to)

    rows = _build_rows(primary, dims, metric_ids, compare, comparison_unit)
    full_count = len(rows)
    rows = _sort_rows(rows, spec.get("sort"), dims, metric_ids)
    limit = min(spec.get("limit") or HARD_ROW_LIMIT, HARD_ROW_LIMIT)
    truncated = full_count > limit
    rows = rows[:limit]

    tg = totals.get((), {"metrics": {}})
    ctg = compare_totals.get((), {"metrics": {}}) if compare_totals is not None else None
    totals_out = {
        "metrics": {mid: _num(tg["metrics"].get(mid)) for mid in metric_ids},
        "deltas": (
            {mid: _delta(tg["metrics"].get(mid), ctg["metrics"].get(mid), comparison_unit) for mid in metric_ids}
            if ctg is not None else None
        ),
    }

    result = {
        "columns": _build_columns(dims, metric_ids),
        "rows": rows,
        "totals": totals_out,
        "meta": {
            "row_count": len(rows),
            "basis": basis,
            "date_range": _window_meta(date_from, date_to),
            "comparison": _window_meta(cmp_from, cmp_to) if cmp_from is not None else None,
            # CR-046 — so renderers know whether deltas are fractions (pct) or absolute
            # amounts (abs); only meaningful when a comparison is present.
            "comparison_unit": comparison_unit if cmp_from is not None else None,
            "currency": basis["currency"],
            "truncated": truncated,
            "unavailable": unavailable,
            "usd_missing_count": ctx.usd_missing_count,
        },
    }
    if viz in ("line", "area", "bar"):
        result["series"] = _build_series(primary, compare, dims, metric_ids, spec)
    return result
