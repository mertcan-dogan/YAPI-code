"""Financing-cost settings + computation (CR-015).

CR-015-A: the effective-settings resolver (project override → company default;
basis is company-level). CR-015-B: ``compute_financing_cost`` — a MODELED accrual
on the months a project is underwater, computed in USD via CR-014 rates.

THE GOVERNING RULE (§0.2): financing is a forecast OVERLAY, never an actual cost.
This module never creates cost_entries, never touches actual totals/margin or the
budget tree. Its total feeds ONLY the separable forecast-with-financing figures.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.calculations.money import D, money
from app.models.company import Company
from app.models.project import Project


def _month_end(year: int, month: int) -> date:
    """Last calendar day of the month (CR-014 walk-back maps it to the last
    business-day rate)."""
    return date(year, month, monthrange(year, month)[1])


def _zeroed_result(eff: dict) -> dict:
    rate = eff["annual_rate_pct"]
    return {
        "enabled": eff["enabled"],
        "annual_rate_pct": str(rate) if rate is not None else None,
        "basis": eff["basis"],
        "total_usd": "0.00",
        "total_try": "0.00",
        "months": [],
    }


def compute_financing_cost(db: Session, project: Project, today: date | None = None) -> dict:
    """Modeled financing cost (§0.3). For each cashflow month the project is
    underwater, accrue simple monthly interest on the financed amount, in USD via
    ``fx.rate_as_of`` then back to TRY. Disabled (effective toggle off / no rate)
    returns a zeroed result — never raises.

    Basis (company-level): ``cumulative`` (default, financially correct — finance
    the negative cumulative position) or ``net`` (per-month negative net). Simple
    accrual: the financing cost is NOT compounded on itself.
    """
    # Lazy import avoids a circular dependency (financials imports this module).
    from app.services import fx
    from app.services.financials import project_cashflow

    company = db.get(Company, project.company_id)
    eff = effective_financing(company, project)
    result = _zeroed_result(eff)

    rate_pct = eff["annual_rate_pct"]
    if not eff["enabled"] or rate_pct is None:
        return result

    monthly_factor = D(rate_pct) / D(100) / D(12)  # simple monthly accrual
    rows = project_cashflow(db, project, today=today)

    # First pass: find the underwater months + their financed amounts. PERF: do
    # this BEFORE touching FX so we resolve every month's rate in ONE batched,
    # CACHE-ONLY query — never a per-month synchronous TCMB fetch inside the web
    # request (a project whose timeline runs past the cached rates would otherwise
    # trigger dozens of blocking 10s HTTP calls). interest_try is rate-independent
    # (the rate cancels); only interest_usd needs a rate, for which the most recent
    # cached rate on/before the month is correct (and, for months past the cache,
    # the latest cached rate).
    underwater = []
    for row in rows:
        base = D(row["net_try"]) if eff["basis"] == "net" else D(row["cumulative_try"])
        if base >= 0:
            continue  # not underwater this month → finances nothing
        underwater.append((row, -base, _month_end(row["year"], row["month_num"])))

    rate_by_date = fx.cached_rates_on_or_before(db, [d for _, _, d in underwater])

    total_usd = D(0)
    total_try = D(0)
    months: list[dict] = []
    for row, financed_try, month_end in underwater:
        rate = rate_by_date.get(month_end)
        if rate is None or rate <= 0:
            continue  # no cached rate on/before this month → can't model it (never error)
        financed_usd = financed_try / rate
        interest_usd = money(financed_usd * monthly_factor)
        # TRY interest at this month's rate == financed_try × factor (rate cancels).
        interest_try = money(financed_try * monthly_factor)
        total_usd += interest_usd
        total_try += interest_try
        months.append({
            "month": row["month"],
            "financed_try": str(money(financed_try)),
            "rate": str(rate),
            "interest_usd": str(interest_usd),
            "interest_try": str(interest_try),
        })

    result["total_usd"] = str(money(total_usd))
    result["total_try"] = str(money(total_try))
    result["months"] = months
    return result


def effective_financing_enabled(company, project=None) -> bool:
    """Project override (if set) beats the company default."""
    if project is not None and project.financing_enabled_override is not None:
        return bool(project.financing_enabled_override)
    return bool(company.financing_enabled)


def effective_financing_rate(company, project=None) -> Decimal | None:
    """Effective USD annual financing rate: project override → company default."""
    if project is not None and project.financing_annual_rate_pct_override is not None:
        return project.financing_annual_rate_pct_override
    return company.financing_annual_rate_pct


def effective_financing(company, project=None) -> dict:
    """The resolved financing settings for a project (basis is company-level)."""
    return {
        "enabled": effective_financing_enabled(company, project),
        "annual_rate_pct": effective_financing_rate(company, project),
        "basis": company.financing_basis,
    }
