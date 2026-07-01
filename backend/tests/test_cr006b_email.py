"""CR-006-B: Resend e-posta bildirimleri.

- RESEND_API_KEY yokken servis çalışır, hata fırlatmaz, loglar.
- send_overdue_cost_email çağrılınca Resend API'ye istek gider.
- Gönderim hatası uygulamayı çökertmez.
- Marj %5 altına düşünce trigger çalışır (24 saat dedup).

Davet akışı (POST /settings/invites + kabul) artık test_cr041_invites.py'de.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.budget_line_item import BudgetLineItem
from app.services.email_service import EmailService, email_service


@pytest.fixture(autouse=True)
def _reset_margin_cache():
    from app.services.triggers import reset_margin_email_cache

    reset_margin_email_cache()
    yield
    reset_margin_email_cache()


def _fake_cost():
    return SimpleNamespace(
        supplier_name="Test Tedarikçi", total_with_vat_try=Decimal("50000"),
        amount_paid_try=Decimal("0"), payment_due_date=None,
    )


# --- Service degrades gracefully without a key ------------------------------
def test_service_disabled_without_key():
    svc = EmailService(api_key="")
    assert svc.enabled is False
    result = svc.send_overdue_cost_email(_fake_cost(), SimpleNamespace(name="P", id="1"), ["a@b.com"])
    assert result["sent"] is False
    assert result["reason"] == "no_api_key"


# --- Real send path hits the Resend SDK -------------------------------------
def test_send_overdue_cost_calls_resend(monkeypatch):
    sent = {}

    def fake_send(params):
        sent.update(params)
        return {"id": "email_123"}

    import resend

    monkeypatch.setattr(resend.Emails, "send", staticmethod(fake_send))
    svc = EmailService(api_key="re_test_key")
    project = SimpleNamespace(name="Köprü Projesi", id="p1")
    result = svc.send_overdue_cost_email(_fake_cost(), project, ["dir@b.com"])

    assert result["sent"] is True and result["id"] == "email_123"
    assert "Vadesi Geçmiş Ödeme" in sent["subject"]
    assert "Test Tedarikçi" in sent["subject"] and "Köprü Projesi" in sent["subject"]
    assert sent["to"] == ["dir@b.com"]


def test_send_error_does_not_crash(monkeypatch):
    def boom(params):
        raise RuntimeError("network down")

    import resend

    monkeypatch.setattr(resend.Emails, "send", staticmethod(boom))
    svc = EmailService(api_key="re_test_key")
    result = svc.send_overdue_cost_email(_fake_cost(), SimpleNamespace(name="P", id="1"), ["a@b.com"])
    assert result["sent"] is False and result["reason"] == "error"


# --- Margin warning trigger -------------------------------------------------
def test_margin_warning_triggers_below_5pct(db, seed, monkeypatch):
    a = seed["a"]
    # Forecast final cost 980k on a 1M contract -> %2 margin (< %5).
    db.add(BudgetLineItem(
        project_id=a["project"].id, company_id=a["company"].id, cost_category="materials",
        original_budget_try=Decimal("900000"), forecast_final_try=Decimal("980000"),
    ))
    db.commit()

    captured = {}
    monkeypatch.setattr(email_service, "send_margin_warning_email",
                        lambda project, margin, recipients: captured.update(
                            {"margin": margin, "recipients": recipients}) or {"sent": True})

    from app.services.triggers import check_margin_warning

    assert check_margin_warning(db, a["project"]) is True
    assert captured["margin"] < 5
    # Director + proje müdürü alıcı listesinde.
    assert any("director" in e for e in captured["recipients"])


def test_margin_warning_not_triggered_when_healthy(db, seed, monkeypatch):
    a = seed["a"]
    db.add(BudgetLineItem(
        project_id=a["project"].id, company_id=a["company"].id, cost_category="materials",
        original_budget_try=Decimal("500000"), forecast_final_try=Decimal("500000"),
    ))
    db.commit()
    monkeypatch.setattr(email_service, "send_margin_warning_email",
                        lambda *args, **kw: pytest.fail("sağlıklı marjda e-posta gönderilmemeli"))
    from app.services.triggers import check_margin_warning

    assert check_margin_warning(db, a["project"]) is False


def test_margin_warning_dedup_within_24h(db, seed, monkeypatch):
    a = seed["a"]
    db.add(BudgetLineItem(
        project_id=a["project"].id, company_id=a["company"].id, cost_category="materials",
        original_budget_try=Decimal("900000"), forecast_final_try=Decimal("980000"),
    ))
    db.commit()
    count = {"n": 0}
    monkeypatch.setattr(email_service, "send_margin_warning_email",
                        lambda *a, **k: count.__setitem__("n", count["n"] + 1) or {"sent": True})
    from app.services.triggers import check_margin_warning

    now = datetime.now(timezone.utc)
    assert check_margin_warning(db, a["project"], now=now) is True
    # İkinci çağrı 1 saat sonra — gönderilmemeli.
    assert check_margin_warning(db, a["project"], now=now + timedelta(hours=1)) is False
    # 25 saat sonra tekrar gönderilebilir.
    assert check_margin_warning(db, a["project"], now=now + timedelta(hours=25)) is True
    assert count["n"] == 2
