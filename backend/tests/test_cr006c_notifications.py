"""CR-006-C: uygulama içi bildirim zili (notifications tablosu + API)."""
from decimal import Decimal

from app.constants import ROLE_DIRECTOR, ROLE_FINANCE
from app.models.budget_line_item import BudgetLineItem
from app.services.notifications import create_notification


def _seed_notif(db, company, **kw):
    kw.setdefault("title", "Test Bildirim")
    kw.setdefault("body", "Açıklama")
    kw.setdefault("type", "ai_alert")
    n = create_notification(db, company_id=company.id, **kw)
    db.commit()
    return n


# --- Table & empty state ----------------------------------------------------
def test_list_empty(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get("/api/v1/notifications")
    assert r.status_code == 200, r.text
    assert r.json()["data"] == []


def test_unread_count_zero(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get("/api/v1/notifications/unread-count")
    assert r.status_code == 200
    assert r.json()["data"]["count"] == 0


# --- Creation increases badge ----------------------------------------------
def test_create_increments_unread_count(client, db, seed):
    _seed_notif(db, seed["a"]["company"], title="Bütçe aşımı", type="budget_overrun", severity="high")
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    assert client.get("/api/v1/notifications/unread-count").json()["data"]["count"] == 1
    data = client.get("/api/v1/notifications").json()["data"]
    assert len(data) == 1 and data[0]["title"] == "Bütçe aşımı"
    assert data[0]["is_read"] is False and data[0]["severity"] == "high"


def test_unread_listed_first(client, db, seed):
    a = seed["a"]["company"]
    n_read = _seed_notif(db, a, title="Okundu")
    _seed_notif(db, a, title="Okunmadı")
    # Mark the first one read directly.
    from app.models.notification import Notification

    db.get(Notification, n_read.id).is_read = True
    db.commit()

    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    data = client.get("/api/v1/notifications").json()["data"]
    assert data[0]["title"] == "Okunmadı"  # unread first


# --- Mark read --------------------------------------------------------------
def test_mark_read_changes_state(client, db, seed):
    n = _seed_notif(db, seed["a"]["company"], title="Marj")
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.put(f"/api/v1/notifications/{n.id}/read")
    assert r.status_code == 200
    assert r.json()["data"]["is_read"] is True
    assert r.json()["data"]["read_at"] is not None
    assert client.get("/api/v1/notifications/unread-count").json()["data"]["count"] == 0


def test_mark_all_read(client, db, seed):
    a = seed["a"]["company"]
    _seed_notif(db, a, title="A")
    _seed_notif(db, a, title="B")
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.put("/api/v1/notifications/read-all")
    assert r.json()["data"]["marked"] == 2
    assert client.get("/api/v1/notifications/unread-count").json()["data"]["count"] == 0


def test_delete_notification(client, db, seed):
    n = _seed_notif(db, seed["a"]["company"], title="Sil")
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    assert client.delete(f"/api/v1/notifications/{n.id}").status_code == 200
    assert client.get("/api/v1/notifications").json()["data"] == []


# --- Company scoping --------------------------------------------------------
def test_company_isolation(client, db, seed):
    _seed_notif(db, seed["b"]["company"], title="B şirketi bildirimi")
    client.login(seed["a"]["users"][ROLE_DIRECTOR])  # company A user
    assert client.get("/api/v1/notifications").json()["data"] == []


# --- Trigger integration ----------------------------------------------------
def test_low_margin_creates_notification(db, seed):
    a = seed["a"]
    db.add(BudgetLineItem(
        project_id=a["project"].id, company_id=a["company"].id, cost_category="materials",
        original_budget_try=Decimal("900000"), forecast_final_try=Decimal("980000"),  # %2 margin
    ))
    db.commit()

    from app.services.triggers import notify_cost_change

    notify_cost_change(db, a["project"])
    from app.models.notification import Notification
    from sqlalchemy import select

    rows = db.execute(select(Notification).where(
        Notification.notification_type == "margin_warning")).scalars().all()
    assert len(rows) == 1 and rows[0].severity == "high"
    # Dedup: ikinci çağrı yeni bildirim oluşturmamalı (okunmamış zaten var).
    notify_cost_change(db, a["project"])
    rows2 = db.execute(select(Notification).where(
        Notification.notification_type == "margin_warning")).scalars().all()
    assert len(rows2) == 1


def test_invoice_collect_creates_notification(client, db, seed):
    """Hakediş tahsil edilince invoice_received bildirimi oluşur."""
    a = seed["a"]
    client.login(a["users"][ROLE_DIRECTOR])
    # Create an invoice.
    r = client.post(f"/api/v1/projects/{a['project'].id}/invoices", json={
        "invoice_number": "INV-001", "invoice_date": "2026-06-01", "amount_try": "100000",
        "vat_rate": "20", "retention_amount_try": "0", "due_date": "2026-06-30",
    })
    assert r.status_code == 200, r.text
    inv_id = r.json()["data"]["id"]
    # Mark it received/paid (date_received auto-fills amount to net_due => paid).
    r2 = client.put(f"/api/v1/projects/{a['project'].id}/invoices/{inv_id}", json={
        "date_received": "2026-06-15",
    })
    assert r2.status_code == 200, r2.text

    data = client.get("/api/v1/notifications").json()["data"]
    assert any(n["type"] == "invoice_received" for n in data)
