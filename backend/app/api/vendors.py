"""CR-008-H — Tedarikçiler (vendor management) endpoints.

Read + write CRUD for the canonical vendor entity: list with spend, merge
duplicate clusters (CR-008-F suggestions), edit aliases, and link legacy
``vendor_id IS NULL`` rows. Writes are normal user-driven CRUD (auth + audit) —
NOT the agent (the agent stays read-only). All queries filter company_id
explicitly (service-role bypasses RLS). Vendor merges/relinks change financial
groupings, so they are written to audit_log (§10.1).
"""
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calculations.money import D, money
from app.config import settings
from app.constants import COST_CATEGORIES
from app.db import get_db
from app.deps import CurrentUser
from app.middleware.limits import enforce_user_limit
from app.models.cost_entry import CostEntry
from app.models.project import Project
from app.models.subcontractor import Subcontractor
from app.models.vendor import Vendor, VendorAlias
from app.responses import APIError, success
from app.services.agent_tools import normalize_vendor_name
from app.services.audit import record_audit
from app.services.vendor_backfill import find_duplicate_clusters

router = APIRouter(prefix="/vendors", tags=["vendors"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _rate_limit(user) -> None:
    enforce_user_limit(user.id, "vendor_write", settings.vendor_write_rate_per_minute)


def _get_vendor(db: Session, company_id, vendor_id) -> Vendor:
    v = db.execute(
        select(Vendor).where(
            Vendor.id == vendor_id, Vendor.company_id == company_id, Vendor.is_deleted.is_(False)
        )
    ).scalar_one_or_none()
    if v is None:
        raise APIError(404, "NOT_FOUND", "Tedarikçi bulunamadı")
    return v


# --------------------------------------------------------------------------- #
# List with spend
# --------------------------------------------------------------------------- #
@router.get("")
def list_vendors(user: CurrentUser, db: Session = Depends(get_db)):
    cid = user.company_id
    vendors = db.execute(
        select(Vendor).where(Vendor.company_id == cid, Vendor.is_deleted.is_(False)).order_by(Vendor.canonical_name)
    ).scalars().all()

    # Spend per vendor (SQL aggregate), excluding pending/unapproved (dashboard parity).
    spend = {
        r[0]: r for r in db.execute(
            select(
                CostEntry.vendor_id,
                func.coalesce(func.sum(CostEntry.amount_try), 0),
                func.count(CostEntry.id),
                func.count(func.distinct(CostEntry.project_id)),
            ).where(
                CostEntry.company_id == cid, CostEntry.is_deleted.is_(False),
                CostEntry.pending_approval.is_(False), CostEntry.vendor_id.is_not(None),
            ).group_by(CostEntry.vendor_id)
        ).all()
    }
    alias_counts = {
        r[0]: r[1] for r in db.execute(
            select(VendorAlias.vendor_id, func.count(VendorAlias.id)).where(
                VendorAlias.company_id == cid, VendorAlias.is_deleted.is_(False)
            ).group_by(VendorAlias.vendor_id)
        ).all()
    }

    rows = []
    for v in vendors:
        s = spend.get(v.id)
        rows.append({
            "id": str(v.id),
            "canonical_name": v.canonical_name,
            "tax_id": v.tax_id,
            "total_try": str(money(s[1])) if s else "0.00",
            "cost_entry_count": int(s[2]) if s else 0,
            "project_count": int(s[3]) if s else 0,
            "alias_count": int(alias_counts.get(v.id, 0)),
        })
    rows.sort(key=lambda r: D(r["total_try"]), reverse=True)
    return success(rows)


@router.get("/suggestions")
def merge_suggestions(user: CurrentUser, db: Session = Depends(get_db)):
    """Likely-duplicate clusters for human review (CR-008-F). Never auto-merged."""
    return success(find_duplicate_clusters(db, user.company_id))


@router.get("/{vendor_id}/aliases")
def list_aliases(vendor_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    _get_vendor(db, user.company_id, vendor_id)
    aliases = db.execute(
        select(VendorAlias).where(
            VendorAlias.vendor_id == vendor_id, VendorAlias.company_id == user.company_id,
            VendorAlias.is_deleted.is_(False),
        ).order_by(VendorAlias.alias_name)
    ).scalars().all()
    return success([{"id": str(a.id), "alias_name": a.alias_name} for a in aliases])


# --------------------------------------------------------------------------- #
# Merge duplicates
# --------------------------------------------------------------------------- #
class MergeRequest(BaseModel):
    survivor_id: uuid.UUID
    merged_ids: list[uuid.UUID] = Field(min_length=1)


@router.post("/merge")
def merge_vendors(payload: MergeRequest, request: Request, user: CurrentUser, db: Session = Depends(get_db)):
    """Merge ``merged_ids`` into ``survivor_id``: relink rows, move aliases,
    soft-delete the merged vendors. Audited (financial grouping change)."""
    _rate_limit(user)
    cid = user.company_id
    if payload.survivor_id in payload.merged_ids:
        raise APIError(422, "VALIDATION_ERROR", "Hedef tedarikçi birleştirilenler arasında olamaz")

    survivor = _get_vendor(db, cid, payload.survivor_id)
    merged = [_get_vendor(db, cid, mid) for mid in payload.merged_ids]  # all must be owned

    merged_ids = [m.id for m in merged]
    relinked_cost = 0
    for c in db.execute(
        select(CostEntry).where(CostEntry.company_id == cid, CostEntry.vendor_id.in_(merged_ids))
    ).scalars().all():
        c.vendor_id = survivor.id
        relinked_cost += 1
    relinked_sub = 0
    for s in db.execute(
        select(Subcontractor).where(Subcontractor.company_id == cid, Subcontractor.vendor_id.in_(merged_ids))
    ).scalars().all():
        s.vendor_id = survivor.id
        relinked_sub += 1

    # Move merged vendors' aliases to the survivor; keep their canonical name as an alias.
    existing = {
        a.alias_normalised for a in db.execute(
            select(VendorAlias).where(VendorAlias.vendor_id == survivor.id, VendorAlias.is_deleted.is_(False))
        ).scalars().all()
    }
    for a in db.execute(
        select(VendorAlias).where(VendorAlias.company_id == cid, VendorAlias.vendor_id.in_(merged_ids))
    ).scalars().all():
        a.vendor_id = survivor.id
    for m in merged:
        norm = normalize_vendor_name(m.canonical_name)
        if norm and norm not in existing:
            db.add(VendorAlias(vendor_id=survivor.id, company_id=cid,
                               alias_name=m.canonical_name, alias_normalised=norm))
            existing.add(norm)
        m.is_deleted = True

    record_audit(
        db, company_id=cid, user_id=user.id, table_name="vendors",
        record_id=survivor.id, action="MERGE",
        old_values={"merged_ids": [str(i) for i in merged_ids]},
        new_values={"survivor": survivor.canonical_name, "relinked_cost_entries": relinked_cost,
                    "relinked_subcontractors": relinked_sub},
        ip_address=_client_ip(request),
    )
    db.commit()
    return success({
        "survivor_id": str(survivor.id),
        "merged": len(merged_ids),
        "relinked_cost_entries": relinked_cost,
        "relinked_subcontractors": relinked_sub,
    })


# --------------------------------------------------------------------------- #
# Aliases
# --------------------------------------------------------------------------- #
class AliasAdd(BaseModel):
    alias_name: str = Field(min_length=1, max_length=255)


@router.post("/{vendor_id}/aliases")
def add_alias(vendor_id: uuid.UUID, payload: AliasAdd, user: CurrentUser, db: Session = Depends(get_db)):
    _rate_limit(user)
    _get_vendor(db, user.company_id, vendor_id)
    norm = normalize_vendor_name(payload.alias_name)
    if not norm:
        raise APIError(422, "VALIDATION_ERROR", "Geçersiz takma ad")
    dup = db.execute(
        select(VendorAlias).where(
            VendorAlias.vendor_id == vendor_id, VendorAlias.alias_normalised == norm,
            VendorAlias.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if dup is not None:
        return success({"id": str(dup.id), "alias_name": dup.alias_name})
    alias = VendorAlias(vendor_id=vendor_id, company_id=user.company_id,
                        alias_name=payload.alias_name.strip(), alias_normalised=norm)
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return success({"id": str(alias.id), "alias_name": alias.alias_name})


@router.delete("/{vendor_id}/aliases/{alias_id}")
def remove_alias(vendor_id: uuid.UUID, alias_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    _rate_limit(user)
    alias = db.execute(
        select(VendorAlias).where(
            VendorAlias.id == alias_id, VendorAlias.vendor_id == vendor_id,
            VendorAlias.company_id == user.company_id, VendorAlias.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if alias is None:
        raise APIError(404, "NOT_FOUND", "Takma ad bulunamadı")
    alias.is_deleted = True
    db.commit()
    return success({"deleted": str(alias_id)})


# --------------------------------------------------------------------------- #
# Legacy unlinked rows + linking
# --------------------------------------------------------------------------- #
@router.get("/unlinked")
def unlinked_rows(user: CurrentUser, db: Session = Depends(get_db)):
    """Cost/subcontractor rows with vendor_id IS NULL, for manual assignment."""
    cid = user.company_id
    suppliers = [
        {"supplier_name": r[0], "count": int(r[1])}
        for r in db.execute(
            select(CostEntry.supplier_name, func.count(CostEntry.id)).where(
                CostEntry.company_id == cid, CostEntry.is_deleted.is_(False),
                CostEntry.vendor_id.is_(None), CostEntry.supplier_name.is_not(None),
            ).group_by(CostEntry.supplier_name).order_by(CostEntry.supplier_name)
        ).all()
    ]
    subs = [
        {"id": str(s.id), "name": s.name, "project_id": str(s.project_id)}
        for s in db.execute(
            select(Subcontractor).where(
                Subcontractor.company_id == cid, Subcontractor.is_deleted.is_(False),
                Subcontractor.vendor_id.is_(None),
            ).order_by(Subcontractor.name)
        ).scalars().all()
    ]
    return success({"suppliers": suppliers, "subcontractors": subs})


class LinkRequest(BaseModel):
    supplier_names: list[str] = Field(default_factory=list)
    subcontractor_ids: list[uuid.UUID] = Field(default_factory=list)


@router.post("/{vendor_id}/link")
def link_rows(vendor_id: uuid.UUID, payload: LinkRequest, request: Request, user: CurrentUser, db: Session = Depends(get_db)):
    """Assign unlinked legacy rows to this vendor, recording their spellings as
    aliases so future matching is exact."""
    _rate_limit(user)
    cid = user.company_id
    vendor = _get_vendor(db, cid, vendor_id)
    if not payload.supplier_names and not payload.subcontractor_ids:
        raise APIError(422, "VALIDATION_ERROR", "Bağlanacak kayıt seçilmedi")

    existing = {
        a.alias_normalised for a in db.execute(
            select(VendorAlias).where(VendorAlias.vendor_id == vendor_id, VendorAlias.is_deleted.is_(False))
        ).scalars().all()
    }

    def _ensure_alias(raw: str | None):
        norm = normalize_vendor_name(raw or "")
        if norm and norm not in existing:
            db.add(VendorAlias(vendor_id=vendor_id, company_id=cid, alias_name=(raw or "").strip(), alias_normalised=norm))
            existing.add(norm)

    linked_cost = 0
    if payload.supplier_names:
        for c in db.execute(
            select(CostEntry).where(
                CostEntry.company_id == cid, CostEntry.is_deleted.is_(False),
                CostEntry.vendor_id.is_(None), CostEntry.supplier_name.in_(payload.supplier_names),
            )
        ).scalars().all():
            c.vendor_id = vendor_id
            linked_cost += 1
        for nm in payload.supplier_names:
            _ensure_alias(nm)

    linked_sub = 0
    if payload.subcontractor_ids:
        for s in db.execute(
            select(Subcontractor).where(
                Subcontractor.company_id == cid, Subcontractor.is_deleted.is_(False),
                Subcontractor.vendor_id.is_(None), Subcontractor.id.in_(payload.subcontractor_ids),
            )
        ).scalars().all():
            s.vendor_id = vendor_id
            _ensure_alias(s.name)
            linked_sub += 1

    record_audit(
        db, company_id=cid, user_id=user.id, table_name="vendors",
        record_id=vendor.id, action="UPDATE",
        new_values={"linked_cost_entries": linked_cost, "linked_subcontractors": linked_sub},
        ip_address=_client_ip(request),
    )
    db.commit()
    return success({"linked_cost_entries": linked_cost, "linked_subcontractors": linked_sub})


# --------------------------------------------------------------------------- #
# Vendor detail (drill-down) — declared last so static routes above win.
# --------------------------------------------------------------------------- #
@router.get("/{vendor_id}")
def vendor_detail(vendor_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """Single-vendor drill-down: canonical name, aliases, total spend and
    by-project / by-category breakdowns, plus linked row counts. Spend mirrors
    the list endpoint — approved cost entries linked to this canonical vendor."""
    cid = user.company_id
    vendor = _get_vendor(db, cid, vendor_id)

    base = [
        CostEntry.company_id == cid,
        CostEntry.is_deleted.is_(False),
        CostEntry.pending_approval.is_(False),
        CostEntry.vendor_id == vendor.id,
    ]

    totals = db.execute(
        select(
            func.coalesce(func.sum(CostEntry.amount_try), 0),
            func.count(CostEntry.id),
            func.count(func.distinct(CostEntry.project_id)),
        ).where(*base)
    ).one()

    project_names = {
        r[0]: r[1] for r in db.execute(
            select(Project.id, Project.name).where(Project.company_id == cid)
        ).all()
    }
    by_project = [
        {
            "project_id": str(r[0]),
            "project_name": project_names.get(r[0], str(r[0])),
            "total_try": str(money(r[1])),
        }
        for r in db.execute(
            select(CostEntry.project_id, func.coalesce(func.sum(CostEntry.amount_try), 0))
            .where(*base).group_by(CostEntry.project_id)
        ).all()
    ]
    by_project.sort(key=lambda r: D(r["total_try"]), reverse=True)

    by_category = [
        {
            "category": r[0],
            "category_label": COST_CATEGORIES.get(r[0], r[0]),
            "total_try": str(money(r[1])),
        }
        for r in db.execute(
            select(CostEntry.cost_category, func.coalesce(func.sum(CostEntry.amount_try), 0))
            .where(*base).group_by(CostEntry.cost_category)
        ).all()
    ]
    by_category.sort(key=lambda r: D(r["total_try"]), reverse=True)

    aliases = db.execute(
        select(VendorAlias.alias_name).where(
            VendorAlias.vendor_id == vendor.id, VendorAlias.company_id == cid,
            VendorAlias.is_deleted.is_(False),
        ).order_by(VendorAlias.alias_name)
    ).scalars().all()

    subcontractor_count = db.execute(
        select(func.count(Subcontractor.id)).where(
            Subcontractor.company_id == cid, Subcontractor.is_deleted.is_(False),
            Subcontractor.vendor_id == vendor.id,
        )
    ).scalar_one()

    return success({
        "id": str(vendor.id),
        "canonical_name": vendor.canonical_name,
        "tax_id": vendor.tax_id,
        "aliases": list(aliases),
        "total_try": str(money(totals[0])),
        "cost_entry_count": int(totals[1]),
        "project_count": int(totals[2]),
        "subcontractor_count": int(subcontractor_count),
        "by_project": by_project,
        "by_category": by_category,
    })
