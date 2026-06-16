"""Financing-cost settings + (later) computation (CR-015).

CR-015-A provides only the effective-settings resolver: a project override wins
over the company default; basis is company-level. The modeled accrual itself
(``compute_financing_cost``) lands in CR-015-B and reads these effective values.
Financing is a MODELED forecast overlay — never an actual cost (§0.2).
"""
from decimal import Decimal


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
