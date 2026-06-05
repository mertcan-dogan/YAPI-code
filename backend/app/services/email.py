"""Transactional email via Resend (Section 10.2). All emails in Turkish.

Degrades gracefully: if RESEND_API_KEY is unset the call is a no-op (logged),
so the app keeps working in development without email configured.
"""
import logging

from app.config import settings

logger = logging.getLogger("yapi.email")

PRIMARY = "#1B2B4B"


def _wrap_html(title: str, body_html: str) -> str:
    return f"""
    <div style="font-family: Arial, sans-serif; color:#1E293B; max-width:560px; margin:0 auto;">
      <div style="background:{PRIMARY}; color:#fff; padding:16px 20px; font-size:18px; font-weight:700;">Yapı</div>
      <div style="padding:20px; border:1px solid #E2E8F0; border-top:none;">
        <h2 style="color:{PRIMARY}; font-size:16px;">{title}</h2>
        {body_html}
        <p style="color:#94A3B8; font-size:12px; margin-top:24px;">
          Bu e-posta Yapı İnşaat Proje Yönetim Yazılımı tarafından otomatik olarak gönderilmiştir.
        </p>
      </div>
    </div>
    """


def _send(to: str | list[str], subject: str, html: str) -> bool:
    if not settings.resend_api_key:
        logger.info("E-posta gönderimi atlandı (RESEND_API_KEY yok): %s -> %s", subject, to)
        return False
    try:
        import resend

        resend.api_key = settings.resend_api_key
        resend.Emails.send(
            {
                "from": settings.email_from,
                "to": to if isinstance(to, list) else [to],
                "subject": subject,
                "html": html,
            }
        )
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("E-posta gönderilemedi: %s", exc)
        return False


def send_user_invitation(email: str, full_name: str, company_name: str) -> bool:
    subject = f"[Yapı] Şirkete Davet Edildiniz: {company_name}"
    link = f"{settings.frontend_url}/signup?email={email}"
    html = _wrap_html(
        "Şirkete Davet Edildiniz",
        f"<p>Merhaba {full_name},</p>"
        f"<p><b>{company_name}</b> şirketi sizi Yapı platformuna davet etti.</p>"
        f'<p><a href="{link}" style="background:{PRIMARY}; color:#fff; padding:10px 16px; '
        f'text-decoration:none; border-radius:6px;">Hesabınızı Oluşturun</a></p>',
    )
    return _send(email, subject, html)


def send_overdue_cost(recipients: list[str], supplier: str, project: str, amount: str) -> bool:
    subject = f"[Yapı] Vadesi Geçmiş Ödeme: {supplier} — {project}"
    html = _wrap_html(
        "Vadesi Geçmiş Ödeme",
        f"<p><b>{project}</b> projesinde <b>{supplier}</b> için {amount} tutarındaki ödemenin vadesi geçmiştir.</p>",
    )
    return _send(recipients, subject, html)


def send_overdue_invoice(recipients: list[str], invoice_no: str, project: str) -> bool:
    subject = f"[Yapı] Tahsil Edilemeyen Hakediş: {invoice_no} — {project}"
    html = _wrap_html(
        "Tahsil Edilemeyen Hakediş",
        f"<p><b>{project}</b> projesinde <b>{invoice_no}</b> numaralı hakedişin vadesi geçmiştir.</p>",
    )
    return _send(recipients, subject, html)


def send_margin_critical(recipients: list[str], project: str, margin: str) -> bool:
    subject = f"[Yapı] ACİL: Kar Marjı Kritik Seviyede — {project}"
    html = _wrap_html(
        "ACİL: Kar Marjı Kritik",
        f"<p><b>{project}</b> projesinin kar marjı {margin} seviyesine düşmüştür. Acil inceleme gereklidir.</p>",
    )
    return _send(recipients, subject, html)


def send_weekly_summary(recipient: str, company_name: str, html_body: str) -> bool:
    subject = f"[Yapı] Haftalık Proje Özeti — {company_name}"
    return _send(recipient, subject, _wrap_html("Haftalık Proje Özeti", html_body))
