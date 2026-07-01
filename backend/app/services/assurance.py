"""CR-022 — Finans Güvence: deterministic, READ-ONLY anomaly rule pack.

Governing principle (§0.2):
  1. READ-ONLY. The rule functions and ``collect_findings`` write NOTHING — they
     only read and return candidate finding dicts. The dedup-aware writer lives in
     ``scan_company`` (CR-022-B) and creates only ``AIAlert`` rows; it never
     touches a cost/invoice/financial figure (mandatory money-untouched test).
  2. Review, not accusation — every string is "incele / olağandışı / yinelenmiş
     olabilir", NEVER "hata/hile/yolsuzluk".
  3. Honest confidence — the cost-outlier rule requires a minimum comparable
     sample and is suppressed below it (no false precision).
  4. Don't nag — every finding carries a stable ``dedup_key`` so a re-scan and the
     writer can skip an issue already raised/dismissed.
  5. Deterministic v1 — pure rules + templated Turkish reasoning, no LLM, no data
     leaves the process.
  6. Rounding tolerance — arithmetic (KDV) checks use ±1.00 TRY.

Candidate dict shape (consumed by ``scan_company``)::

    {alert_type, severity, project_id, source_type, source_id,
     dedup_key, title_tr, body_tr, reasoning, recommended_action}
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations.money import D
from app.constants import COST_CATEGORIES
from app.models.ai_alert import AIAlert
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.project import Project
from app.utils.format import format_number_tr

logger = logging.getLogger("yapi.assurance")

# --- thresholds / tolerances (§0.2) ---------------------------------------- #
KDV_TOLERANCE = D("1.00")                       # ±1 TRY rounding tolerance
VALID_VAT_RATES = {D("0"), D("1"), D("10"), D("20")}
TOLERATED_VAT_RATES = {D("8"), D("18")}         # legacy rates — tolerate, don't flag
OUTLIER_MIN_SAMPLE = 5                           # ≥5 comparable OTHER records required
OUTLIER_FACTOR = D("3")                          # amount > median(others) × 3
DUP_DATE_WINDOW_DAYS = 2


def _try(value) -> str:
    """Turkish-grouped whole-TRY string, e.g. '48.000 ₺'."""
    return f"{format_number_tr(value, 0)} ₺"


def _finding(*, alert_type, severity, project_id, source_type, source_id,
             dedup_key, title_tr, body_tr, reasoning, recommended_action=None) -> dict:
    return {
        "alert_type": alert_type,
        "severity": severity,
        "project_id": project_id,
        "source_type": source_type,
        "source_id": source_id,
        "dedup_key": dedup_key,
        "title_tr": title_tr,
        "body_tr": body_tr,
        "reasoning": reasoning,
        "recommended_action": recommended_action,
    }


# --------------------------------------------------------------------------- #
# Data load — fetch once per company, then evaluate the rules in memory. The
# per-company record set is bounded; this mirrors alert_engine's existing
# fetch-then-evaluate pattern and stays dialect-portable (no percentile_cont).
# --------------------------------------------------------------------------- #
def _load(db: Session, company_id):
    costs = db.execute(
        select(CostEntry).where(
            CostEntry.company_id == company_id, CostEntry.is_deleted.is_(False)
        )
    ).scalars().all()
    invoices = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.company_id == company_id, ClientInvoice.is_deleted.is_(False)
        )
    ).scalars().all()
    projects = db.execute(
        select(Project).where(
            Project.company_id == company_id, Project.is_deleted.is_(False)
        )
    ).scalars().all()
    return costs, invoices, projects


def scanned_counts(db: Session, company_id) -> dict:
    """How many records the scan looked at — the honest basis for the stat."""
    costs, invoices, _ = _load(db, company_id)
    return {"cost_entries": len(costs), "client_invoices": len(invoices)}


# --------------------------------------------------------------------------- #
# Rule 1 — duplicate records (duplicate_cost / duplicate_invoice)
# --------------------------------------------------------------------------- #
def _dup_cost_key(c):
    """Group key for a cost entry: vendor first, else a non-empty description.
    Returns None when there is too little to dedup on (avoids false positives)."""
    if c.vendor_id is not None:
        return ("v", str(c.vendor_id))
    desc = (c.description or "").strip().lower()
    return ("d", desc) if desc else None


def _emit_duplicate_pairs(records, *, group_key, get_date, alert_type, source_type, kind_tr):
    findings: list[dict] = []
    groups: dict = defaultdict(list)
    for r in records:
        k = group_key(r)
        if k is None:
            continue
        groups[k].append(r)
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda r: (get_date(r) or date.min, str(r.id)))
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                da, dbb = get_date(a), get_date(b)
                if not (da and dbb) or abs((da - dbb).days) > DUP_DATE_WINDOW_DAYS:
                    continue
                ids = sorted([str(a.id), str(b.id)])
                primary = a if str(a.id) == ids[0] else b
                other = b if primary is a else a
                amt = _try(a.amount_try)
                reasoning = (
                    f"İki {kind_tr} aynı tutarda ({amt}) ve tarihleri birbirine "
                    f"{abs((da - dbb).days)} gün içinde — yinelenmiş olabilir. "
                    "İncelemeniz önerilir."
                )
                findings.append(_finding(
                    alert_type=alert_type, severity="high",
                    project_id=primary.project_id,
                    source_type=source_type, source_id=primary.id,
                    dedup_key=f"{alert_type}:{ids[0]}|{ids[1]}",
                    title_tr="Yinelenen kayıt",
                    body_tr=(
                        f"Aynı tutarda ({amt}) iki {kind_tr} bulundu "
                        f"(kayıtlar: {ids[0]}, {ids[1]}). Mükerrer olabilir."
                    ),
                    reasoning=reasoning,
                    recommended_action="Yinelenen kaydı silin veya birleştirin.",
                ))
    return findings


def find_duplicates(costs, invoices) -> list[dict]:
    out = _emit_duplicate_pairs(
        costs,
        group_key=lambda c: (
            (c.project_id, _dup_cost_key(c), D(c.amount_try)) if _dup_cost_key(c) else None
        ),
        get_date=lambda c: c.entry_date,
        alert_type="duplicate_cost", source_type="cost_entry", kind_tr="maliyet kaydı",
    )
    out += _emit_duplicate_pairs(
        invoices,
        group_key=lambda inv: (inv.project_id, D(inv.amount_try)),
        get_date=lambda inv: inv.invoice_date,
        alert_type="duplicate_invoice", source_type="client_invoice", kind_tr="hakediş",
    )
    return out


# --------------------------------------------------------------------------- #
# Rule 2 — cost outlier (vendor or category/subcategory norm × 3)
# --------------------------------------------------------------------------- #
def _outlier_group_key(c):
    if c.vendor_id is not None:
        return ("v", str(c.vendor_id))
    return ("c", c.cost_category, c.subcategory or "")


def find_cost_outliers(costs) -> list[dict]:
    findings: list[dict] = []
    groups: dict = defaultdict(list)
    for c in costs:
        if c.entry_type == "actual":
            groups[_outlier_group_key(c)].append(c)
    for c in costs:
        if c.entry_type != "actual":
            continue
        group = groups[_outlier_group_key(c)]
        others = [D(o.amount_try) for o in group if o.id != c.id]
        # Honest confidence: need ≥5 comparable others, else suppress (§0.2.3).
        if len(others) < OUTLIER_MIN_SAMPLE:
            continue
        median = D(str(statistics.median(others)))
        if median <= 0:
            continue
        amount = D(c.amount_try)
        if amount > median * OUTLIER_FACTOR:
            factor = (amount / median).quantize(D("0.1"))
            label = (
                "bu tedarikçinin" if c.vendor_id is not None
                else f"'{COST_CATEGORIES.get(c.cost_category, c.cost_category)}' kategorisinin"
            )
            findings.append(_finding(
                alert_type="cost_outlier", severity="medium",
                project_id=c.project_id, source_type="cost_entry", source_id=c.id,
                dedup_key=f"cost_outlier:{c.id}",
                title_tr="Olağandışı maliyet",
                body_tr=(
                    f"Bir maliyet ({_try(amount)}) {label} geçmiş medyanının "
                    f"({_try(median)}) yaklaşık {factor} katı."
                ),
                reasoning=(
                    f"Bu maliyet {_try(amount)} — {label} geçmiş medyanının "
                    f"({_try(median)}, {len(others)} kayıt) yaklaşık {factor} katı. "
                    "Olağandışı görünüyor; incelemeniz önerilir."
                ),
                recommended_action="İlgili maliyet kaydını ve tutarı doğrulayın.",
            ))
    return findings


# --------------------------------------------------------------------------- #
# Rule 3 — KDV / total mismatch (cost_entries + client_invoices)
# --------------------------------------------------------------------------- #
def _kdv_finding(rec, source_type) -> dict | None:
    base = D(rec.amount_try)
    vat = D(rec.vat_amount_try)
    total = D(rec.total_with_vat_try)
    rate = D(rec.vat_rate)
    reasons: list[str] = []

    if abs(total - (base + vat)) > KDV_TOLERANCE:
        reasons.append(
            f"toplam ({_try(total)}) ile ana tutar + KDV ({_try(base)} + {_try(vat)}) uyuşmuyor"
        )
    expected_vat = (base * rate / D("100"))
    if abs(vat - expected_vat) > KDV_TOLERANCE:
        reasons.append(
            f"KDV tutarı ({_try(vat)}) %{format_number_tr(rate, 0)} oran için beklenenden "
            f"({_try(expected_vat)}) farklı"
        )
    if rate not in VALID_VAT_RATES and rate not in TOLERATED_VAT_RATES:
        reasons.append(f"KDV oranı (%{format_number_tr(rate, 0)}) standart oranlardan değil")

    if not reasons:
        return None
    return _finding(
        alert_type="kdv_mismatch", severity="high",
        project_id=rec.project_id, source_type=source_type, source_id=rec.id,
        dedup_key=f"kdv_mismatch:{source_type}:{rec.id}",
        title_tr="KDV / toplam tutarsızlığı",
        body_tr="Bu kayıtta KDV/toplam değerleri tutarsız görünüyor.",
        reasoning="Bu kayıtta " + "; ".join(reasons) + ". İncelemeniz önerilir.",
        recommended_action="KDV oranı ve tutarlarını kontrol edin.",
    )


def find_kdv_mismatches(costs, invoices) -> list[dict]:
    out = []
    for c in costs:
        f = _kdv_finding(c, "cost_entry")
        if f:
            out.append(f)
    for inv in invoices:
        f = _kdv_finding(inv, "client_invoice")
        if f:
            out.append(f)
    return out


# --------------------------------------------------------------------------- #
# Rule 4 — hakediş over contract (project level)
# --------------------------------------------------------------------------- #
def find_hakedis_over_contract(invoices, projects) -> list[dict]:
    by_project: dict = defaultdict(lambda: D(0))
    for inv in invoices:
        by_project[inv.project_id] += D(inv.amount_try)
    findings = []
    for p in projects:
        total = by_project.get(p.id, D(0))
        contract = D(p.contract_value_try or 0)
        if contract > 0 and total > contract:
            findings.append(_finding(
                alert_type="hakedis_over_contract", severity="high",
                project_id=p.id, source_type="project", source_id=p.id,
                dedup_key=f"hakedis_over_contract:{p.id}",
                title_tr="Hakediş sözleşmeyi aşıyor",
                body_tr=(
                    f"Toplam hakediş ({_try(total)}) sözleşme bedelini "
                    f"({_try(contract)}) aşıyor."
                ),
                reasoning=(
                    f"Bu projede toplam hakediş tutarı {_try(total)}, sözleşme bedeli "
                    f"{_try(contract)} — sözleşme aşılmış görünüyor. İncelemeniz önerilir."
                ),
                recommended_action="Hakediş tutarlarını ve sözleşme bedelini gözden geçirin.",
            ))
    return findings


# --------------------------------------------------------------------------- #
# Rule 5 — missing FX (amount_try set but amount_usd NULL), per project
# --------------------------------------------------------------------------- #
def find_missing_fx(costs, invoices) -> list[dict]:
    counts: dict = defaultdict(int)
    for r in costs + invoices:
        if r.amount_try is not None and r.amount_usd is None:
            counts[r.project_id] += 1
    findings = []
    for pid, n in counts.items():
        findings.append(_finding(
            alert_type="missing_fx", severity="low",
            project_id=pid, source_type="project", source_id=pid,
            dedup_key=f"missing_fx:{pid}",
            title_tr="Eksik kur (USD) bilgisi",
            body_tr=f"{n} kayıtta USD karşılığı (kur) eksik.",
            reasoning=(
                f"Bu projede {n} kayıtta USD karşılığı (kur) bulunmuyor; içe aktarımdan "
                "kalmış olabilir. İncelemeniz önerilir."
            ),
            recommended_action="Eksik kur bilgisini tamamlayın.",
        ))
    return findings


# --------------------------------------------------------------------------- #
# Rule 6 — unlinked vendor (cost_entries with no vendor and no subcontractor)
# --------------------------------------------------------------------------- #
def find_unlinked_vendors(costs) -> list[dict]:
    counts: dict = defaultdict(int)
    for c in costs:
        if c.vendor_id is None and c.subcontractor_id is None:
            counts[c.project_id] += 1
    findings = []
    for pid, n in counts.items():
        findings.append(_finding(
            alert_type="unlinked_vendor", severity="low",
            project_id=pid, source_type="project", source_id=pid,
            dedup_key=f"unlinked_vendor:{pid}",
            title_tr="Tedarikçiye bağlanmamış maliyet",
            body_tr=f"{n} maliyet kaydı bir tedarikçiye bağlanmamış.",
            reasoning=(
                f"Bu projede {n} maliyet kaydı bir tedarikçi (veya alt yüklenici) ile "
                "eşleştirilmemiş. İncelemeniz önerilir."
            ),
            recommended_action="İlgili maliyet kayıtlarını bir tedarikçiyle eşleştirin.",
        ))
    return findings


# --------------------------------------------------------------------------- #
# Rule 7 — non-positive amount (data-entry sanity), per record
# --------------------------------------------------------------------------- #
def find_nonpositive_amounts(costs, invoices) -> list[dict]:
    findings = []
    for rec, source_type, kind in (
        [(c, "cost_entry", "maliyet kaydı") for c in costs]
        + [(inv, "client_invoice", "hakediş") for inv in invoices]
    ):
        if D(rec.amount_try) <= 0:
            findings.append(_finding(
                alert_type="nonpositive_amount", severity="medium",
                project_id=rec.project_id, source_type=source_type, source_id=rec.id,
                dedup_key=f"nonpositive_amount:{source_type}:{rec.id}",
                title_tr="Sıfır veya negatif tutar",
                body_tr=f"Bu {kind} tutarı {_try(rec.amount_try)} görünüyor.",
                reasoning=(
                    f"Bu {kind} tutarı {_try(rec.amount_try)} — sıfır veya negatif. "
                    "Veri girişi hatası olabilir; incelemeniz önerilir."
                ),
                recommended_action="Tutarı kontrol edin ve düzeltin.",
            ))
    return findings


# --------------------------------------------------------------------------- #
# Aggregate entry — READ-ONLY: returns candidates, writes nothing.
# --------------------------------------------------------------------------- #
def collect_findings(db: Session, company_id, today: date | None = None) -> list[dict]:
    """Run the whole rule pack and return candidate findings (no writes).

    Resilient: a failing rule is logged and skipped so one bad rule can never
    abort the whole scan (§2.1 'never raises; log + continue per rule')."""
    costs, invoices, projects = _load(db, company_id)
    rules = (
        ("duplicates", lambda: find_duplicates(costs, invoices)),
        ("cost_outliers", lambda: find_cost_outliers(costs)),
        ("kdv_mismatches", lambda: find_kdv_mismatches(costs, invoices)),
        ("hakedis_over_contract", lambda: find_hakedis_over_contract(invoices, projects)),
        ("missing_fx", lambda: find_missing_fx(costs, invoices)),
        ("unlinked_vendors", lambda: find_unlinked_vendors(costs)),
        ("nonpositive_amounts", lambda: find_nonpositive_amounts(costs, invoices)),
    )
    findings: list[dict] = []
    for name, rule in rules:
        try:
            findings += rule()
        except Exception:  # noqa: BLE001 - one rule must never abort the scan
            logger.exception("[assurance] rule %s failed; skipping", name)
    return findings


# --------------------------------------------------------------------------- #
# CR-022-B — dedup-aware writer + scan entrypoint.
# This is the ONLY code here that writes, and it writes ONLY AIAlert rows — never
# a cost/invoice/financial figure (mandatory money-untouched guard test).
# --------------------------------------------------------------------------- #
def _suppressed_dedup_keys(db: Session, company_id, keys: set) -> set:
    """dedup_keys whose existing alert should suppress a re-creation: the most
    recent alert for that key is active, OR dismissed but still within its
    dismissal window. A dismissed alert whose window has passed is NOT suppressed
    (it re-surfaces, mirroring the 7-day health-alert behavior)."""
    if not keys:
        return set()
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(AIAlert)
        .where(AIAlert.company_id == company_id, AIAlert.dedup_key.in_(list(keys)))
        .order_by(AIAlert.created_at.desc())
    ).scalars().all()
    latest: dict = {}
    for a in rows:
        latest.setdefault(a.dedup_key, a)  # first seen = most recent (desc order)
    suppress = set()
    for key, a in latest.items():
        du = a.dismissed_until
        if du is not None and du.tzinfo is None:
            du = du.replace(tzinfo=timezone.utc)  # SQLite returns naive; treat as UTC
        if not a.is_dismissed or (du is not None and du > now):
            suppress.add(key)
    return suppress


def _write_finding(db: Session, company_id, c: dict) -> None:
    db.add(AIAlert(
        company_id=company_id,
        project_id=c["project_id"],
        alert_type=c["alert_type"],
        severity=c["severity"],
        title_tr=c["title_tr"],
        body_tr=c["body_tr"],
        reasoning=c["reasoning"],
        recommended_action=c["recommended_action"],
        source_type=c["source_type"],
        source_id=c["source_id"],
        dedup_key=c["dedup_key"],
    ))


def scan_company(db: Session, company_id, today: date | None = None) -> dict:
    """Run the rule pack and upsert findings as AIAlert rows with per-issue dedup.

    Read-only w.r.t. financial data: it only creates AIAlert rows. Never raises —
    a per-candidate write failure is logged and skipped. Returns an honest summary
    of what was scanned vs found (the basis for the 'Finans Güvence' stat)."""
    counts = scanned_counts(db, company_id)
    candidates = collect_findings(db, company_id, today)

    found: dict = defaultdict(int)
    for c in candidates:
        found[c["alert_type"]] += 1

    suppress = _suppressed_dedup_keys(db, company_id, {c["dedup_key"] for c in candidates})
    created = 0
    for c in candidates:
        if c["dedup_key"] in suppress:
            continue
        try:
            _write_finding(db, company_id, c)
            suppress.add(c["dedup_key"])  # don't double-create within one scan
            created += 1
        except Exception:  # noqa: BLE001 - never let one finding abort the scan
            logger.exception("[assurance] failed to write finding %s", c.get("dedup_key"))
    db.commit()
    return {
        "scanned": counts,
        "found": dict(found),
        "total_found": len(candidates),
        "created": created,
    }
