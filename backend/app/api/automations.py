"""CR-012 — Otomasyonlar CRUD (company-level template config + run history).

The Automations page lists the two curated templates as cards; the director
enables/configures each one here. Document-auto-file is event-driven (no
schedule); recurring-digest is scheduled and its ``next_run_at`` is (re)computed
whenever it is enabled or its cadence changes. Every enable/disable/config change
is audited (``automations`` is in AUDITED_TABLES).
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, DirectorUser
from app.models.automation import (
    TEMPLATE_DOCUMENT_AUTO_FILE,
    TEMPLATE_KEYS,
    TEMPLATE_RECURRING_DIGEST,
    Automation,
    AutomationRun,
)
from app.responses import APIError, success
from app.services import automations as automations_service
from app.services.audit import record_audit, snapshot

router = APIRouter(tags=["automations"])

# Static catalogue — title/description/kind + the founder's default config per
# template. The DB only stores a company's overrides; this is the source of truth
# for what the cards render and the defaults a fresh automation starts from.
TEMPLATE_CATALOG: dict[str, dict] = {
    TEMPLATE_DOCUMENT_AUTO_FILE: {
        "title": "Belge Otomatik Dosyalama",
        "description": (
            "Yüklenen fatura/belgeyi Yapı AI sınıflandırır, alanları çıkarır ve nereye "
            "kaydedileceğini önerir. Öneri Onay Bekleyenler'e düşer — siz onaylamadan "
            "hiçbir kayıt oluşmaz."
        ),
        "kind": "event",
        "default_config": {
            "min_confidence": 0.75,
            "destinations": ["cost", "client_invoice"],
            "default_project_id": None,
        },
    },
    TEMPLATE_RECURRING_DIGEST: {
        "title": "Periyodik Özet",
        "description": (
            "Haftalık veya aylık olarak proje/portföy özetini hazırlar ve uygulama içi "
            "bildirim olarak iletir (e-posta, doğrulanmış alan adı eklendiğinde best-effort)."
        ),
        "kind": "scheduled",
        "default_config": {
            "cadence": "weekly",
            "day_of_week": 0,
            "day_of_month": 1,
            "hour": 8,
            "tz": automations_service.DEFAULT_TZ,
            "scope": "all",
            "delivery": {"in_app": True, "email": False},
        },
    },
}

DESTINATION_SUBSET = {"cost", "client_invoice"}


def _validate_config(template_key: str, config: dict) -> dict:
    """Normalise + validate a config against its template; raise 422 on bad input."""
    cfg = dict(config or {})
    if template_key == TEMPLATE_RECURRING_DIGEST:
        cadence = cfg.get("cadence", "weekly")
        if cadence not in ("weekly", "monthly"):
            raise APIError(422, "VALIDATION_ERROR", "Geçersiz tekrar aralığı", field="cadence")
        hour = int(cfg.get("hour", automations_service.DEFAULT_HOUR))
        if not 0 <= hour <= 23:
            raise APIError(422, "VALIDATION_ERROR", "Saat 0-23 arasında olmalı", field="hour")
        cfg["hour"] = hour
        if cadence == "weekly":
            dow = int(cfg.get("day_of_week", 0))
            if not 0 <= dow <= 6:
                raise APIError(422, "VALIDATION_ERROR", "Geçersiz gün", field="day_of_week")
            cfg["day_of_week"] = dow
        else:
            dom = int(cfg.get("day_of_month", 1))
            if not 1 <= dom <= 28:
                raise APIError(422, "VALIDATION_ERROR", "Ayın günü 1-28 arasında olmalı", field="day_of_month")
            cfg["day_of_month"] = dom
        cfg.setdefault("tz", automations_service.DEFAULT_TZ)
        cfg.setdefault("scope", "all")
        delivery = cfg.get("delivery") or {}
        cfg["delivery"] = {"in_app": bool(delivery.get("in_app", True)), "email": bool(delivery.get("email", False))}
    elif template_key == TEMPLATE_DOCUMENT_AUTO_FILE:
        try:
            mc = float(cfg.get("min_confidence", 0.75))
        except (TypeError, ValueError):
            raise APIError(422, "VALIDATION_ERROR", "Geçersiz güven eşiği", field="min_confidence")
        if not 0 <= mc <= 1:
            raise APIError(422, "VALIDATION_ERROR", "Güven eşiği 0-1 arasında olmalı", field="min_confidence")
        cfg["min_confidence"] = mc
        dests = cfg.get("destinations") or ["cost", "client_invoice"]
        dests = [d for d in dests if d in DESTINATION_SUBSET]
        if not dests:
            raise APIError(422, "VALIDATION_ERROR", "En az bir hedef seçmelisiniz", field="destinations")
        cfg["destinations"] = dests
    return cfg


def _get_automation(db: Session, company_id: uuid.UUID, template_key: str) -> Automation | None:
    return db.execute(
        select(Automation).where(
            Automation.company_id == company_id,
            Automation.template_key == template_key,
            Automation.is_deleted.is_(False),
        )
    ).scalar_one_or_none()


def _last_run(db: Session, automation_id: uuid.UUID) -> AutomationRun | None:
    return db.execute(
        select(AutomationRun)
        .where(AutomationRun.automation_id == automation_id, AutomationRun.is_deleted.is_(False))
        .order_by(AutomationRun.started_at.desc())
        .limit(1)
    ).scalars().first()


def _view(db: Session, company_id: uuid.UUID, template_key: str) -> dict:
    """Merge the catalogue + the company's stored automation into one card view."""
    cat = TEMPLATE_CATALOG[template_key]
    auto = _get_automation(db, company_id, template_key)
    config = dict(cat["default_config"])
    if auto and auto.config:
        config.update(auto.config)
    last = _last_run(db, auto.id) if auto else None
    return {
        "template_key": template_key,
        "title": cat["title"],
        "description": cat["description"],
        "kind": cat["kind"],
        "id": str(auto.id) if auto else None,
        "enabled": bool(auto.enabled) if auto else False,
        "config": config,
        "last_run_at": auto.last_run_at.isoformat() if auto and auto.last_run_at else None,
        "next_run_at": auto.next_run_at.isoformat() if auto and auto.next_run_at else None,
        "last_run": {
            "status": last.status,
            "summary": last.summary,
            "started_at": last.started_at.isoformat() if last.started_at else None,
        } if last else None,
    }


@router.get("/automations")
def list_automations(user: CurrentUser, db: Session = Depends(get_db)):
    """Both curated templates as cards (enabled/config/last-run), real data."""
    items = [_view(db, user.company_id, k) for k in (TEMPLATE_DOCUMENT_AUTO_FILE, TEMPLATE_RECURRING_DIGEST)]
    return success(items, meta={"total": len(items)})


class AutomationUpdate(BaseModel):
    enabled: bool
    config: dict | None = None


@router.put("/automations/{template_key}")
def upsert_automation(template_key: str, payload: AutomationUpdate, user: DirectorUser, db: Session = Depends(get_db)):
    """Enable/disable + configure a template for the company (director only)."""
    if template_key not in TEMPLATE_KEYS:
        raise APIError(404, "NOT_FOUND", "Bilinmeyen otomasyon şablonu")
    cfg = _validate_config(template_key, payload.config or {})

    auto = _get_automation(db, user.company_id, template_key)
    is_new = auto is None
    old = snapshot(auto) if auto else None
    if auto is None:
        auto = Automation(
            company_id=user.company_id, template_key=template_key,
            created_by=user.id, config=cfg, enabled=payload.enabled,
        )
        db.add(auto)
    else:
        auto.config = cfg
        auto.enabled = payload.enabled

    # Scheduled templates: (re)compute the next fire whenever enabled, so cadence
    # edits take effect immediately. Event-driven templates have no schedule.
    if template_key == TEMPLATE_RECURRING_DIGEST and payload.enabled:
        auto.next_run_at = automations_service.compute_next_run(cfg, datetime.now(timezone.utc))
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="automations",
        record_id=auto.id, action="INSERT" if is_new else "UPDATE",
        old_values=old, new_values=snapshot(auto),
    )
    db.commit()
    return success(_view(db, user.company_id, template_key))


@router.get("/automations/runs")
def list_runs(user: CurrentUser, db: Session = Depends(get_db), template_key: str | None = None, limit: int = 20):
    """Recent run history (company-wide, newest first) for the run-history panel."""
    q = select(AutomationRun).where(
        AutomationRun.company_id == user.company_id,
        AutomationRun.is_deleted.is_(False),
    )
    if template_key:
        q = q.where(AutomationRun.template_key == template_key)
    rows = db.execute(q.order_by(AutomationRun.started_at.desc()).limit(min(limit, 100))).scalars().all()
    data = [
        {
            "id": str(r.id),
            "template_key": r.template_key,
            "status": r.status,
            "summary": r.summary,
            "error": r.error,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in rows
    ]
    return success(data, meta={"total": len(data)})
