"""RAG (Red/Amber/Green) status computation (Section 7.3).

Computed in real time on every API call that returns project data.
"""


def compute_rag_status(project_financials: dict) -> str:
    margin_pct = project_financials["margin_pct"]
    overdue_count = project_financials["overdue_count"]
    overdue_days_max = project_financials["max_overdue_days"]
    cash_position = project_financials["net_cash_position"]
    budget_overrun_categories = project_financials["categories_over_100pct"]

    # RED conditions (any one triggers red)
    if (
        margin_pct < 5
        or margin_pct < 0
        or cash_position < 0
        or overdue_days_max > 60
        or budget_overrun_categories > 2
    ):
        return "red"

    # AMBER conditions (any one triggers amber)
    if margin_pct < 10 or overdue_count > 0 or overdue_days_max > 30:
        return "amber"

    return "green"


# Turkish status labels for the RAG badge (Section 4.1 "Durum")
RAG_LABELS_TR = {"red": "Kritik", "amber": "Dikkat", "green": "İyi"}


def rag_reason_tr(project_financials: dict) -> str:
    """Human-readable Turkish reason shown in the RAG tooltip (Section 6.5)."""
    margin_pct = project_financials["margin_pct"]
    overdue_count = project_financials["overdue_count"]
    overdue_days_max = project_financials["max_overdue_days"]
    cash_position = project_financials["net_cash_position"]
    over = project_financials["categories_over_100pct"]

    reasons: list[str] = []
    if margin_pct < 0:
        reasons.append("Kar marjı negatif")
    elif margin_pct < 5:
        reasons.append(f"Kar marjı kritik (%{margin_pct:.1f})")
    elif margin_pct < 10:
        reasons.append(f"Kar marjı düşük (%{margin_pct:.1f})")
    if cash_position < 0:
        reasons.append("Nakit pozisyonu negatif")
    if overdue_days_max > 60:
        reasons.append(f"{overdue_days_max} gün geciken ödeme")
    elif overdue_days_max > 30:
        reasons.append(f"{overdue_days_max} gün geciken ödeme")
    elif overdue_count > 0:
        reasons.append(f"{overdue_count} vadesi geçmiş ödeme")
    if over > 0:
        reasons.append(f"{over} kategori bütçe aşımında")

    return " · ".join(reasons) if reasons else "Tüm göstergeler sağlıklı"
