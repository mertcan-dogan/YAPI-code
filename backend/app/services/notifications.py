"""CR-006-C: bildirim oluşturma yardımcısı + tetikleyiciler.

Her trigger noktası ``create_notification`` çağırarak notifications tablosuna
kayıt ekler. Helper, kaydı session'a ekler ve döndürür; commit çağıranın
sorumluluğundadır (mevcut işlemle aynı transaction'da kalsın diye).
"""
import uuid

from sqlalchemy.orm import Session

from app.models.notification import Notification

VALID_TYPES = {
    "overdue_payment", "margin_warning", "budget_overrun", "invoice_received", "ai_alert",
}
VALID_SEVERITIES = {"high", "medium", "low"}


def create_notification(
    db: Session,
    company_id: uuid.UUID,
    title: str,
    body: str,
    type: str,
    severity: str = "medium",
    project_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> Notification:
    """notifications tablosuna yeni bir kayıt ekler (commit etmez)."""
    notif = Notification(
        company_id=company_id,
        user_id=user_id,
        title=title,
        body=body,
        notification_type=type if type in VALID_TYPES else "ai_alert",
        severity=severity if severity in VALID_SEVERITIES else "medium",
        related_project_id=project_id,
    )
    db.add(notif)
    db.flush()
    return notif
