"""CR-006-B: Resend e-posta bildirim servisi.

Tüm e-postalar ortak bir HTML şablonu (koyu lacivert üst bant + beyaz içerik +
gri alt bant) kullanır. RESEND_API_KEY tanımlı değilken servis sessizce devre
dışı kalır — hata fırlatmaz, yalnızca loglar. Gönderim hataları da yakalanır ve
loglanır; e-posta hiçbir koşulda uygulamayı çökertmez.

API anahtarı asla kodda gömülü değildir; her zaman ``settings.resend_api_key``
(yani RESEND_API_KEY ortam değişkeni) üzerinden okunur.
"""
import logging

from app.config import settings
from app.utils.format import format_currency_tr, format_date_tr, format_pct_tr

logger = logging.getLogger("yapi.email")

NAVY = "#1E3A5F"


class EmailService:
    """Thin wrapper over the Resend SDK with Türkçe HTML templates."""

    def __init__(self, api_key: str | None = None, from_email: str | None = None,
                 from_name: str | None = None):
        # ``None`` means "read from settings at call time" so env/monkeypatch wins.
        self._api_key = api_key
        self._from_email = from_email
        self._from_name = from_name

    # -- configuration (read lazily so tests/env can override) ----------------
    @property
    def api_key(self) -> str:
        return self._api_key if self._api_key is not None else settings.resend_api_key

    @property
    def from_address(self) -> str:
        name = self._from_name or settings.resend_from_name
        email = self._from_email or settings.resend_from_email
        return f"{name} <{email}>"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    # -- low-level send -------------------------------------------------------
    def _send(self, to, subject: str, html: str) -> dict:
        """Send one email. Never raises — returns a {'sent': bool, ...} result."""
        recipients = [to] if isinstance(to, str) else [r for r in (to or []) if r]
        if not recipients:
            logger.info("E-posta alıcısı yok, atlandı: %s", subject)
            return {"sent": False, "reason": "no_recipients"}
        if not self.enabled:
            logger.warning("RESEND_API_KEY tanımlı değil — e-posta gönderilmedi: %s", subject)
            return {"sent": False, "reason": "no_api_key"}
        try:
            import resend

            resend.api_key = self.api_key
            result = resend.Emails.send({
                "from": self.from_address,
                "to": recipients,
                "subject": subject,
                "html": html,
            })
            email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
            logger.info("E-posta gönderildi (%s) -> %s", subject, recipients)
            return {"sent": True, "id": email_id, "result": result}
        except Exception as exc:  # network, auth, SDK missing — must not crash the app.
            logger.error("E-posta gönderim hatası (%s): %s", subject, exc)
            return {"sent": False, "reason": "error", "error": str(exc)}

    # -- shared HTML shell ----------------------------------------------------
    def _wrap(self, heading: str, body_html: str) -> str:
        return (
            '<div style="background:#F1F5F9;padding:24px 0;font-family:Arial,Helvetica,sans-serif;">'
            '<div style="max-width:600px;margin:0 auto;background:#FFFFFF;'
            'border-radius:8px;overflow:hidden;border:1px solid #E2E8F0;">'
            f'<div style="background:{NAVY};padding:18px 24px;">'
            '<span style="color:#FFFFFF;font-size:20px;font-weight:bold;letter-spacing:1px;">YAPI</span>'
            '</div>'
            f'<div style="padding:24px;color:#1E293B;font-size:14px;line-height:1.6;">'
            f'<h2 style="color:{NAVY};font-size:18px;margin:0 0 16px;">{heading}</h2>'
            f'{body_html}'
            '</div>'
            '<div style="background:#F8FAFC;padding:14px 24px;color:#94A3B8;font-size:11px;">'
            'Bu e-posta Yapı tarafından otomatik gönderilmiştir.'
            '</div></div></div>'
        )

    @staticmethod
    def _button(label: str, url: str) -> str:
        return (
            f'<p style="margin:20px 0;"><a href="{url}" '
            f'style="background:{NAVY};color:#FFFFFF;text-decoration:none;padding:10px 20px;'
            'border-radius:6px;display:inline-block;font-weight:bold;">'
            f'{label}</a></p>'
        )

    # -- public templates -----------------------------------------------------
    def send_overdue_cost_email(self, cost, project, recipients) -> dict:
        from app.calculations.money import D

        supplier = getattr(cost, "supplier_name", None) or "Tedarikçi"
        project_name = getattr(project, "name", "")
        remaining = D(getattr(cost, "total_with_vat_try", 0)) - D(getattr(cost, "amount_paid_try", 0))
        due = getattr(cost, "payment_due_date", None)
        days = ""
        if due is not None:
            from datetime import date

            days = max((date.today() - due).days, 0)
        subject = f"[Yapı] Vadesi Geçmiş Ödeme: {supplier} — {project_name}"
        body = (
            f"<p><b>{supplier}</b> tedarikçisine ait ödeme vadesi geçmiştir.</p>"
            "<ul>"
            f"<li>Proje: <b>{project_name}</b></li>"
            f"<li>Tutar: <b>{format_currency_tr(remaining)}</b></li>"
            f"<li>Vade Tarihi: {format_date_tr(due)}</li>"
            f"<li>Gecikme: <b>{days} gün</b></li>"
            "</ul>"
            + self._button("Ödemeyi İşaretle", f"{settings.frontend_url}/projects/{getattr(project, 'id', '')}/costs")
        )
        return self._send(recipients, subject, self._wrap("Vadesi Geçmiş Ödeme", body))

    def send_overdue_invoice_email(self, invoice, project, recipients) -> dict:
        project_name = getattr(project, "name", "")
        number = getattr(invoice, "invoice_number", "")
        outstanding = getattr(invoice, "outstanding_try", 0)
        due = getattr(invoice, "due_date", None)
        subject = f"[Yapı] Tahsil Edilemeyen Hakediş: {number} — {project_name}"
        body = (
            f"<p><b>{number}</b> numaralı hakedişin vadesi geçmiş ve henüz tahsil edilememiştir.</p>"
            "<ul>"
            f"<li>Proje: <b>{project_name}</b></li>"
            f"<li>Bekleyen Tutar: <b>{format_currency_tr(outstanding)}</b></li>"
            f"<li>Vade Tarihi: {format_date_tr(due)}</li>"
            "</ul>"
        )
        return self._send(recipients, subject, self._wrap("Tahsil Edilemeyen Hakediş", body))

    def send_margin_warning_email(self, project, margin_pct, recipients) -> dict:
        project_name = getattr(project, "name", "")
        subject = f"[Yapı] ACİL: Kar Marjı Kritik Seviyede — {project_name}"
        body = (
            f"<p><b>{project_name}</b> projesinin kar marjı kritik seviyeye düşmüştür.</p>"
            f'<p style="font-size:24px;color:#EF4444;font-weight:bold;margin:8px 0;">'
            f"{format_pct_tr(margin_pct)}</p>"
            "<p>Maliyet kontrolü ve bütçe gözden geçirmesi acilen önerilir.</p>"
            + self._button("Projeyi İncele", f"{settings.frontend_url}/projects/{getattr(project, 'id', '')}")
        )
        return self._send(recipients, subject, self._wrap("Kar Marjı Uyarısı", body))

    def send_user_invitation_email(self, email, company_name, invite_token) -> dict:
        subject = f"[Yapı] Şirkete Davet Edildiniz: {company_name}"
        link = f"{settings.frontend_url}/accept-invite?token={invite_token}"
        body = (
            f"<p><b>{company_name}</b> şirketine Yapı'da katılmanız için davet edildiniz.</p>"
            "<p>Aşağıdaki bağlantı 7 gün geçerlidir.</p>"
            + self._button("Daveti Kabul Et", link)
            + f'<p style="color:#94A3B8;font-size:12px;">{link}</p>'
        )
        return self._send(email, subject, self._wrap("Şirkete Davet", body))

    def send_weekly_summary_email(self, company, projects_data, recipient) -> dict:
        company_name = getattr(company, "name", "")
        subject = f"[Yapı] Haftalık Proje Özeti — {company_name}"
        rows = "".join(
            "<tr>"
            f'<td style="padding:6px 8px;border-bottom:1px solid #E2E8F0;">{p.get("name", "")}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #E2E8F0;text-align:right;">'
            f'{p.get("margin", "")}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #E2E8F0;text-align:right;">'
            f'{p.get("outstanding", "")}</td>'
            "</tr>"
            for p in (projects_data or [])
        )
        table = (
            '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
            f'<tr style="background:{NAVY};color:#FFFFFF;">'
            '<th style="padding:6px 8px;text-align:left;">Proje</th>'
            '<th style="padding:6px 8px;text-align:right;">Marj</th>'
            '<th style="padding:6px 8px;text-align:right;">Bekleyen</th></tr>'
            f"{rows}</table>"
        ) if rows else "<p>Bu hafta aktif proje bulunmamaktadır.</p>"
        body = f"<p>{company_name} portföyünün haftalık özeti:</p>{table}"
        return self._send(recipient, subject, self._wrap("Haftalık Proje Özeti", body))


# Module-level singleton used by trigger points.
email_service = EmailService()
