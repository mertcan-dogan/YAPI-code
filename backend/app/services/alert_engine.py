"""AI alert engine — evaluates the 5 trigger conditions (Section 5.2).

Trigger conditions are evaluated deterministically in Python; Claude is used
only to compose the Turkish narrative (with a deterministic fallback). Alerts
are de-duplicated: an active (non-dismissed) alert of the same type for the same
project is not recreated, and dismissed alerts stay hidden for 7 days (Section 5.5).
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations.money import D, safe_div
from app.calculations.subcontractor import subcontractor_revised_contract
from app.models.ai_alert import AIAlert
from app.models.cost_entry import CostEntry
from app.models.project import Project
from app.models.subcontractor import Subcontractor
from app.services import ai as ai_service
from app.services.financials import forecast_at_completion, project_financials


def _has_active(db: Session, company_id, project_id, alert_type: str) -> bool:
    now = datetime.now(timezone.utc)
    existing = db.execute(
        select(AIAlert).where(
            AIAlert.company_id == company_id,
            AIAlert.project_id == project_id,
            AIAlert.alert_type == alert_type,
        ).order_by(AIAlert.created_at.desc())
    ).scalars().first()
    if existing is None:
        return False
    if not existing.is_dismissed:
        return True
    # Dismissed: suppressed for 7 days.
    if existing.dismissed_until and existing.dismissed_until > now:
        return True
    return False


def _add_alert(db: Session, company_id, project_id, alert_type, severity, title, body, action=None, reasoning=None):
    db.add(
        AIAlert(
            company_id=company_id,
            project_id=project_id,
            alert_type=alert_type,
            severity=severity,
            title_tr=title,
            body_tr=body,
            recommended_action=action,
            reasoning=reasoning,
        )
    )


def analyze_project(db: Session, project: Project, today: date | None = None) -> list[dict]:
    """Evaluate all alert conditions for a project and persist new alerts."""
    today = today or date.today()
    f = project_financials(db, project, today=today)
    created: list[dict] = []
    cid = project.company_id

    margin = float(f["margin_pct"])
    target = float(f["target_margin_pct"]) if f["target_margin_pct"] is not None else None

    # Type 1 — Margin warning
    if (margin < 10 or (target is not None and margin < target)) and not _has_active(db, cid, project.id, "margin_warning"):
        summary = {**{k: f[k] for k in ("margin_pct", "target_margin_pct", "contract_value_try",
                                        "forecast_final_cost_try", "revised_budget_try")},
                   "project_name": project.name}
        alert = ai_service.analyze_margin(summary)
        if alert:
            _add_alert(db, cid, project.id, "margin_warning",
                       alert.get("severity", "medium"), alert.get("title", "Kar Marjı Uyarısı"),
                       alert.get("body", ""), alert.get("recommended_action"))
            created.append({"type": "margin_warning", **alert})

    # Type 2 — Cash flow gap (next 45 days): outflows > inflows × 1.3
    horizon = today + timedelta(days=45)
    out_45 = D(0)
    for c in db.execute(select(CostEntry).where(
        CostEntry.project_id == project.id, CostEntry.is_deleted.is_(False),
        CostEntry.payment_status != "paid", CostEntry.payment_due_date.isnot(None),
        CostEntry.payment_due_date <= horizon)).scalars().all():
        out_45 += D(c.total_with_vat_try)
    from app.models.client_invoice import ClientInvoice
    in_45 = D(0)
    for inv in db.execute(select(ClientInvoice).where(
        ClientInvoice.project_id == project.id, ClientInvoice.is_deleted.is_(False),
        ClientInvoice.payment_status != "paid", ClientInvoice.due_date <= horizon)).scalars().all():
        in_45 += D(inv.outstanding_try)
    if out_45 > in_45 * D("1.3") and out_45 > 0 and not _has_active(db, cid, project.id, "cashflow_gap"):
        gap = out_45 - in_45
        _add_alert(db, cid, project.id, "cashflow_gap", "high",
                   "Nakit Akışı Açığı Uyarısı",
                   f"Önümüzdeki 45 günde beklenen gider {out_45:,.0f}₺, beklenen gelir {in_45:,.0f}₺. "
                   f"Yaklaşık {gap:,.0f}₺ nakit açığı oluşabilir.",
                   "Tahsilatları hızlandırın veya ödeme planını yeniden düzenleyin.")
        created.append({"type": "cashflow_gap"})

    # Type 3 — Subcontractor anomaly: paid/revised > 0.90 AND completion < 0.70
    completion = float(f["completion_pct"]) / 100
    for sub in db.execute(select(Subcontractor).where(
        Subcontractor.project_id == project.id, Subcontractor.is_deleted.is_(False))).scalars().all():
        revised = subcontractor_revised_contract(sub.contract_value_try, sub.approved_variations_try)
        paid = D(0)
        for e in db.execute(select(CostEntry).where(
            CostEntry.subcontractor_id == sub.id, CostEntry.is_deleted.is_(False))).scalars().all():
            paid += D(e.amount_paid_try)
        ratio = float(safe_div(paid, revised))
        if ratio > 0.90 and completion < 0.70 and not _has_active(db, cid, project.id, "subcontractor_anomaly"):
            _add_alert(db, cid, project.id, "subcontractor_anomaly", "medium",
                       "Alt Yüklenici Anomalisi",
                       f"Alt yükleniciye ({sub.name}) yapılan ödemeler sözleşme değerinin %90'ına ulaştı "
                       f"ancak iş tamamlanma oranı %70'in altında.",
                       "Alt yüklenici ilerlemesini ve hakedişlerini denetleyin.")
            created.append({"type": "subcontractor_anomaly"})
            break

    # Type 4 — Budget category overrun: faturalanan/revize > 0.95
    if f["categories_over_95pct"] > 0 and not _has_active(db, cid, project.id, "budget_overrun"):
        _add_alert(db, cid, project.id, "budget_overrun", "medium",
                   "Bütçe Kategorisi Aşımı",
                   f"{f['categories_over_95pct']} maliyet kategorisi revize bütçenin %95'ini aştı.",
                   "İlgili kategori harcamalarını ve final tahminlerini gözden geçirin.")
        created.append({"type": "budget_overrun"})

    # Type 5 — Overdue accumulation: count > 3 OR total overdue > 5% of contract
    overdue_total = D(0)
    for c in db.execute(select(CostEntry).where(
        CostEntry.project_id == project.id, CostEntry.is_deleted.is_(False),
        CostEntry.payment_status != "paid", CostEntry.payment_due_date.isnot(None),
        CostEntry.payment_due_date < today)).scalars().all():
        overdue_total += D(c.total_with_vat_try)
    threshold = D(f["contract_value_try"]) * D("0.05")
    if (f["overdue_count"] > 3 or overdue_total > threshold) and not _has_active(db, cid, project.id, "overdue_payment"):
        _add_alert(db, cid, project.id, "overdue_payment", "high",
                   "Vadesi Geçmiş Ödeme Birikimi",
                   f"{f['overdue_count']} adet vadesi geçmiş ödeme bulunuyor "
                   f"(toplam yaklaşık {overdue_total:,.0f}₺).",
                   "Vadesi geçmiş ödemeleri önceliklendirin.")
        created.append({"type": "overdue_payment"})

    created += _extra_alerts(db, project, today, cid)

    db.commit()
    return created


def _extra_alerts(db: Session, project: Project, today: date, cid) -> list[dict]:
    """CR-003-M: 5 additional alert types."""
    from collections import defaultdict

    from app.models.client_invoice import ClientInvoice

    created: list[dict] = []
    costs = db.execute(
        select(CostEntry).where(
            CostEntry.project_id == project.id, CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),
        )
    ).scalars().all()
    invoices = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.project_id == project.id, ClientInvoice.is_deleted.is_(False)
        )
    ).scalars().all()

    # 1) Duplicate invoice numbers (supplier invoices = cost entries; client
    #    invoices already have a unique constraint so cannot duplicate).
    seen_nums: dict[str, int] = defaultdict(int)
    for c in costs:
        if c.invoice_number:
            seen_nums[c.invoice_number] += 1
    dup = [num for num, n in seen_nums.items() if n >= 2]
    if dup and not _has_active(db, cid, project.id, "duplicate_invoice"):
        _add_alert(db, cid, project.id, "duplicate_invoice", "medium", "Yinelenen Fatura",
                   f"{dup[0]} numaralı fatura bu projede daha önce kaydedilmiş. Mükerrer kayıt olabilir.",
                   "Fatura kayıtlarını kontrol edin.")
        created.append({"type": "duplicate_invoice"})

    # 2) Unusual cost: an actual entry > 3x its category average.
    by_cat: dict[str, list] = defaultdict(list)
    for c in costs:
        if c.entry_type == "actual":
            by_cat[c.cost_category].append(D(c.amount_try))
    unusual = None
    for cat, amounts in by_cat.items():
        if len(amounts) >= 2:
            for i, a in enumerate(amounts):
                others = amounts[:i] + amounts[i + 1:]
                others_avg = sum(others) / len(others) if others else D(0)
                if others_avg > 0 and a > others_avg * 3:
                    unusual = cat
                    break
        if unusual:
            break
    if unusual and not _has_active(db, cid, project.id, "unusual_cost"):
        from app.constants import COST_CATEGORIES

        _add_alert(db, cid, project.id, "unusual_cost", "medium", "Olağandışı Maliyet",
                   f"{COST_CATEGORIES.get(unusual, unusual)} kategorisinde bir maliyet, kategori "
                   "ortalamasının 3 katından fazla. İncelemenizi öneririz.",
                   "İlgili maliyet kaydını doğrulayın.")
        created.append({"type": "unusual_cost"})

    # 3) Collection risk: an unpaid invoice 45+ days overdue.
    risky = None
    for inv in invoices:
        if inv.payment_status != "paid" and D(inv.outstanding_try) > 0 and inv.due_date:
            days = (today - inv.due_date).days
            if days >= 45:
                risky = (inv.invoice_number, days)
                break
    if risky and not _has_active(db, cid, project.id, "collection_risk"):
        _add_alert(db, cid, project.id, "collection_risk", "high", "Tahsilat Riski",
                   f"{risky[0]} hakedişi {risky[1]} gündür tahsil edilemedi. İşverenle iletişime geçilmesini öneririz.",
                   "İşverenle tahsilat görüşmesi planlayın.")
        created.append({"type": "collection_risk"})

    # 4) Margin erosion: forecast margin below current and current below 12%.
    f = project_financials(db, project, today=today)
    fac = forecast_at_completion(db, project)
    cur = float(f["margin_pct"])
    fc = float(fac["forecast_final_margin_pct"])
    if cur < 12 and fc < cur and not _has_active(db, cid, project.id, "margin_erosion"):
        _add_alert(db, cid, project.id, "margin_erosion", "high", "Marj Bozulması",
                   f"{project.name} projesinde kar marjı bozuluyor: güncel %{cur:.1f}, tahmini final %{fc:.1f}. "
                   "Acil maliyet kontrolü gerekiyor.",
                   "Final tahminleri ve maliyet kalemlerini gözden geçirin.")
        created.append({"type": "margin_erosion"})

    # 5) 30-day cash gap: outflow > inflow * 1.5.
    horizon = today + timedelta(days=30)
    out_30 = sum((D(c.total_with_vat_try) for c in costs
                  if c.payment_status != "paid" and c.payment_due_date and today <= c.payment_due_date <= horizon), D(0))
    in_30 = sum((D(inv.outstanding_try) for inv in invoices
                 if inv.payment_status != "paid" and inv.due_date and today <= inv.due_date <= horizon), D(0))
    if out_30 > in_30 * D("1.5") and out_30 > 0 and not _has_active(db, cid, project.id, "cash_gap_30"):
        gap = out_30 - in_30
        _add_alert(db, cid, project.id, "cash_gap_30", "high", "Nakit Açığı Riski",
                   f"Önümüzdeki 30 günde {out_30:,.0f}₺ gider öngörüsüne karşın yalnızca {in_30:,.0f}₺ "
                   f"tahsilat bekleniyor. {gap:,.0f}₺ nakit açığı riski.",
                   "Tahsilatları hızlandırın veya ödeme planını revize edin.")
        created.append({"type": "cash_gap_30"})

    return created
