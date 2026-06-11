"""CR-006-B: e-posta tetikleme noktaları (trigger points).

Bu modül iş mantığını (kim, ne zaman e-posta alır) e-posta şablonlarından ayırır.
Tüm tetikleyiciler hata-toleranslıdır: e-posta gönderimi başarısız olsa bile
çağıran isteği (örn. maliyet kaydı oluşturma) asla başarısız olmaz.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import ROLE_DIRECTOR
from app.models.user import User
from app.services.email_service import email_service

logger = logging.getLogger("yapi.email")

# Proje bazında son marj uyarısı zamanı (24 saatte bir gönderim için).
_recent_margin_emails: dict = {}
_MARGIN_THRESHOLD = 5.0


def director_emails(db: Session, company_id) -> list[str]:
    users = db.execute(
        select(User).where(
            User.company_id == company_id,
            User.role == ROLE_DIRECTOR,
            User.is_deleted.is_(False),
        )
    ).scalars().all()
    return [u.email for u in users if u.email]


def project_warning_recipients(db: Session, project) -> list[str]:
    """Director rolündeki kullanıcılar + proje müdürü (benzersiz)."""
    emails = set(director_emails(db, project.company_id))
    pm_id = getattr(project, "project_manager_id", None)
    if pm_id:
        pm = db.get(User, pm_id)
        if pm and pm.email and not pm.is_deleted:
            emails.add(pm.email)
    return sorted(emails)


def check_margin_warning(db: Session, project, now: datetime | None = None) -> bool:
    """Marj %5 altına düştüyse ve son 24 saatte gönderilmediyse uyarı e-postası gönder.

    Returns True if an email send was attempted.
    """
    from app.services.financials import forecast_at_completion

    try:
        fac = forecast_at_completion(db, project)
        margin = float(fac["forecast_final_margin_pct"])
    except Exception as exc:  # never break the caller over a calc error
        logger.error("Marj hesaplama hatası (%s): %s", getattr(project, "id", "?"), exc)
        return False

    if margin >= _MARGIN_THRESHOLD:
        return False

    now = now or datetime.now(timezone.utc)
    last = _recent_margin_emails.get(project.id)
    if last is not None and (now - last) < timedelta(hours=24):
        return False

    recipients = project_warning_recipients(db, project)
    _recent_margin_emails[project.id] = now
    email_service.send_margin_warning_email(project, margin, recipients)
    return True


def reset_margin_email_cache() -> None:
    """Test yardımcısı — gönderim dedup önbelleğini temizle."""
    _recent_margin_emails.clear()


# ---------------------------------------------------------------------------
# CR-006-C: in-app bildirim tetikleyicileri (notifications tablosu)
# ---------------------------------------------------------------------------
def _has_unread(db: Session, company_id, project_id, ntype: str) -> bool:
    """Aynı proje/tip için okunmamış bir bildirim zaten var mı? (tekrar önleme)"""
    from app.models.notification import Notification

    return db.execute(
        select(Notification.id).where(
            Notification.company_id == company_id,
            Notification.related_project_id == project_id,
            Notification.notification_type == ntype,
            Notification.is_read.is_(False),
            Notification.is_deleted.is_(False),
        ).limit(1)
    ).first() is not None


def notify_cost_change(db: Session, project) -> None:
    """Maliyet değişikliği sonrası marj + bütçe aşımı bildirimleri (kendi commit'i).

    Hata-toleranslı: çağıran isteği asla bozmaz.
    """
    try:
        from app.services.financials import forecast_at_completion, project_financials
        from app.services.notifications import create_notification

        created = False
        # Marj bildirimi: < %5 kritik (high), < %10 uyarı (medium).
        fac = forecast_at_completion(db, project)
        margin = float(fac["forecast_final_margin_pct"])
        if margin < _MARGIN_THRESHOLD and not _has_unread(db, project.company_id, project.id, "margin_warning"):
            create_notification(
                db, company_id=project.company_id,
                title=f"{project.name}: Kar marjı kritik (%{margin:.1f})",
                body="Kar marjı %5'in altına düştü. Acil maliyet kontrolü gerekli.",
                type="margin_warning", severity="high", project_id=project.id,
            )
            created = True
        elif margin < 10 and not _has_unread(db, project.company_id, project.id, "margin_warning"):
            create_notification(
                db, company_id=project.company_id,
                title=f"{project.name}: Kar marjı uyarısı (%{margin:.1f})",
                body="Kar marjı %10'un altına düştü.",
                type="margin_warning", severity="medium", project_id=project.id,
            )
            created = True

        # Bütçe aşımı bildirimi: herhangi kategori %95'e ulaşınca.
        fin = project_financials(db, project)
        if fin["categories_over_95pct"] > 0 and not _has_unread(
            db, project.company_id, project.id, "budget_overrun"
        ):
            sev = "high" if fin["categories_over_100pct"] > 0 else "medium"
            create_notification(
                db, company_id=project.company_id,
                title=f"{project.name}: Bütçe aşımı riski",
                body=f"{fin['categories_over_95pct']} kategori bütçesinin %95'ine ulaştı.",
                type="budget_overrun", severity=sev, project_id=project.id,
            )
            created = True

        if created:
            db.commit()
    except Exception as exc:
        logger.error("Bildirim tetikleyici hatası (%s): %s", getattr(project, "id", "?"), exc)


def notify_invoice_received(db: Session, invoice, project) -> None:
    """Hakediş tahsil edildiğinde bilgi bildirimi (çağıranın commit'iyle persist)."""
    try:
        from app.services.notifications import create_notification
        from app.utils.format import format_currency_tr

        create_notification(
            db, company_id=project.company_id,
            title=f"{project.name}: Hakediş tahsil edildi",
            body=f"{getattr(invoice, 'invoice_number', '')} numaralı hakediş için "
                 f"{format_currency_tr(getattr(invoice, 'amount_received_try', 0))} tahsil edildi.",
            type="invoice_received", severity="low", project_id=project.id,
        )
    except Exception as exc:
        logger.error("Tahsilat bildirimi hatası: %s", exc)
