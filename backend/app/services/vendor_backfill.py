"""CR-008-F: conservative vendor backfill.

Per company: create one canonical ``vendors`` row per distinct NORMALISED
supplier/subcontractor name, record raw spellings as ``vendor_aliases``, and link
exact normalised matches to ``vendor_id``. Fuzzy variants are **never** auto-merged
— likely-duplicate clusters are *flagged* for human confirmation in the
Tedarikçiler merge UI (CR-008-H). Additive (existing supplier_name/name kept; only
``vendor_id IS NULL`` rows are linked) and idempotent (safe to re-run).

Run once per company after deploy (§13.6), e.g. via backfill_all_companies(db).

Clustering uses difflib ratio on normalised names (dialect-independent, so the
SQLite test suite exercises it directly). The 0.4 threshold mirrors the CR-007
``pg_trgm`` threshold (§7.1.4); the agent's live matching still uses pg_trgm
(CR-008-G), unchanged.
"""
import logging
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.models.vendor import Vendor, VendorAlias
from app.services.agent_tools import normalize_vendor_name

logger = logging.getLogger("yapi.vendor_backfill")

# CR-007 pg_trgm threshold for the agent's live fuzzy MATCHING (high recall — the
# model then picks the best match). NOT used for merge suggestions.
DUP_THRESHOLD = 0.4
# Merge-SUGGESTION threshold (CR-008-H Tedarikçiler UI). Deliberately MUCH higher
# than DUP_THRESHOLD: a suggestion tells a human "these two are probably the same
# vendor", so it must be a near-exact spelling/diacritic variant, not a loose 40%
# match. Tuned so genuine typos ("Bozkurt Beton"/"Beotn") and diacritic variants
# ("Demir İnşaat"/"Demir Inşaat") are caught while distinct short names
# ("Mehmet Usta"/"Ahmet Usta") are not.
MERGE_SUGGEST_THRESHOLD = 0.86
# Bound the suggestion payload (most-similar first) so a large vendor book can't
# return a huge list to the merge UI.
MAX_MERGE_SUGGESTIONS = 50


def _distinct_raw_names(db: Session, company_id) -> set[str]:
    """Distinct supplier/subcontractor name strings for a company (raw, as stored
    — so IN-clause linking matches the actual rows)."""
    cost = db.execute(
        select(CostEntry.supplier_name).where(
            CostEntry.company_id == company_id,
            CostEntry.is_deleted.is_(False),
            CostEntry.supplier_name.is_not(None),
        ).distinct()
    ).scalars().all()
    sub = db.execute(
        select(Subcontractor.name).where(
            Subcontractor.company_id == company_id,
            Subcontractor.is_deleted.is_(False),
            Subcontractor.name.is_not(None),
        ).distinct()
    ).scalars().all()
    return {n for n in list(cost) + list(sub) if n and n.strip()}


def find_duplicate_clusters(
    db: Session, company_id, threshold: float = MERGE_SUGGEST_THRESHOLD
) -> list[list[dict]]:
    """Likely-duplicate vendor PAIRS for human review (CR-008-H) — never auto-merged.

    Each returned pair is two canonical vendors whose normalised names are
    ``>= threshold`` similar, most-similar first. **Pairwise, NOT transitively
    clustered:** the old union-find at a 0.4 threshold chained unrelated vendors
    (A~B and B~C ⇒ {A, B, C}) into one giant unusable "merge everything" group.
    Emitting independent pairs at a conservative threshold keeps each suggestion
    individually reviewable. The frontend already renders each cluster as its own
    merge card, so a 2-element cluster is the natural unit.
    """
    vendors = db.execute(
        select(Vendor).where(Vendor.company_id == company_id, Vendor.is_deleted.is_(False))
    ).scalars().all()
    items = [(v.id, v.canonical_name, normalize_vendor_name(v.canonical_name)) for v in vendors]
    n = len(items)

    scored: list[tuple[float, int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if items[i][2] == items[j][2]:
                continue  # identical normalised name => already the same vendor
            ratio = SequenceMatcher(None, items[i][2], items[j][2]).ratio()
            if ratio >= threshold:
                scored.append((ratio, i, j))

    scored.sort(key=lambda t: t[0], reverse=True)  # best candidates first
    return [
        [
            {"id": str(items[i][0]), "canonical_name": items[i][1]},
            {"id": str(items[j][0]), "canonical_name": items[j][1]},
        ]
        for _ratio, i, j in scored[:MAX_MERGE_SUGGESTIONS]
    ]


def resolve_or_create_vendor_id(db: Session, company_id, raw_name: str | None):
    """Auto-link a freshly created cost/subcontractor row to a canonical vendor.

    Called at cost-entry / import / capture time so new rows no longer pile up with
    ``vendor_id IS NULL`` until the one-time backfill is re-run. Resolution is
    EXACT-only, using the same normalisation as the backfill: an existing alias or
    canonical-name match links to that vendor; otherwise a new canonical vendor +
    alias is created. Fuzzy near-duplicates are NEVER auto-merged here — that stays
    human-reviewed via ``find_duplicate_clusters`` + the merge UI. Returns the
    ``vendor_id`` (uuid) or ``None`` for a blank name. Idempotent and additive, so
    the same spelling twice yields one vendor.
    """
    if not raw_name or not raw_name.strip():
        return None
    norm = normalize_vendor_name(raw_name)
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
        return alias.vendor_id

    # Defensive: a canonical vendor exists with no alias for this spelling yet.
    for v in db.execute(
        select(Vendor).where(Vendor.company_id == company_id, Vendor.is_deleted.is_(False))
    ).scalars().all():
        if normalize_vendor_name(v.canonical_name) == norm:
            db.add(VendorAlias(vendor_id=v.id, company_id=company_id,
                               alias_name=raw_name.strip(), alias_normalised=norm))
            return v.id

    vendor = Vendor(company_id=company_id, canonical_name=raw_name.strip())
    db.add(vendor)
    db.flush()
    db.add(VendorAlias(vendor_id=vendor.id, company_id=company_id,
                       alias_name=raw_name.strip(), alias_normalised=norm))
    return vendor.id


def backfill_company(db: Session, company_id) -> dict:
    """Idempotent backfill for one company. Returns a summary of what changed."""
    summary = {
        "vendors_created": 0, "aliases_created": 0,
        "cost_entries_linked": 0, "subcontractors_linked": 0,
        "clusters_flagged": 0, "clusters": [],
    }

    # raw spelling -> normalised; group spellings by normalised name.
    groups: dict[str, set[str]] = {}
    for raw in _distinct_raw_names(db, company_id):
        norm = normalize_vendor_name(raw)
        if norm:
            groups.setdefault(norm, set()).add(raw)

    for norm, spellings in groups.items():
        # Reuse an existing vendor if any alias already maps this normalised name
        # (keeps re-runs from creating duplicates).
        alias = db.execute(
            select(VendorAlias).where(
                VendorAlias.company_id == company_id,
                VendorAlias.alias_normalised == norm,
                VendorAlias.is_deleted.is_(False),
            )
        ).scalars().first()
        if alias:
            vendor_id = alias.vendor_id
        else:
            canonical = max(spellings, key=lambda s: (len(s), s)).strip()
            vendor = Vendor(company_id=company_id, canonical_name=canonical)
            db.add(vendor)
            db.flush()
            vendor_id = vendor.id
            summary["vendors_created"] += 1

        existing_aliases = set(db.execute(
            select(VendorAlias.alias_name).where(
                VendorAlias.vendor_id == vendor_id, VendorAlias.is_deleted.is_(False)
            )
        ).scalars().all())
        for raw in spellings:
            if raw not in existing_aliases:
                db.add(VendorAlias(vendor_id=vendor_id, company_id=company_id,
                                   alias_name=raw, alias_normalised=norm))
                summary["aliases_created"] += 1

        spell_list = list(spellings)
        for c in db.execute(
            select(CostEntry).where(
                CostEntry.company_id == company_id, CostEntry.is_deleted.is_(False),
                CostEntry.vendor_id.is_(None), CostEntry.supplier_name.in_(spell_list),
            )
        ).scalars().all():
            c.vendor_id = vendor_id
            summary["cost_entries_linked"] += 1
        for s in db.execute(
            select(Subcontractor).where(
                Subcontractor.company_id == company_id, Subcontractor.is_deleted.is_(False),
                Subcontractor.vendor_id.is_(None), Subcontractor.name.in_(spell_list),
            )
        ).scalars().all():
            s.vendor_id = vendor_id
            summary["subcontractors_linked"] += 1

    db.flush()
    clusters = find_duplicate_clusters(db, company_id)
    summary["clusters"] = clusters
    summary["clusters_flagged"] = len(clusters)
    db.commit()
    logger.info(
        "[vendor_backfill] company=%s vendors=%d aliases=%d cost_links=%d sub_links=%d clusters=%d",
        company_id, summary["vendors_created"], summary["aliases_created"],
        summary["cost_entries_linked"], summary["subcontractors_linked"], summary["clusters_flagged"],
    )
    return summary


def backfill_all_companies(db: Session) -> dict[str, dict]:
    """Run the backfill for every company. The explicit post-deploy step (§13.6)."""
    from app.models.company import Company

    results: dict[str, dict] = {}
    for c in db.execute(select(Company)).scalars().all():
        results[str(c.id)] = backfill_company(db, c.id)
    return results
