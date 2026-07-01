"""CR-041: teammate invitation + acceptance.

Covers the backend half of audit #1 (directors could not add teammates; the
invite link dead-ended and created a brand-new company):

- Director creates a tokenized invite (POST /settings/invites), director-only.
- List + revoke invites, scoped to the director's own company.
- Public token preview (GET /auth/invite/{token}).
- Accept (POST /auth/invite/{token}/accept) creates the user in the INVITING
  company with the invited role — NOT a new company.
- Token hygiene: expired / revoked / already-used tokens are rejected.
- Identity binding: a mismatched signed-in email is refused; an already-attached
  user cannot accept (multi-company membership is out of scope).
- Tenant scoping: a director cannot list/revoke another company's invites.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.constants import (
    INVITE_ACCEPTED,
    INVITE_PENDING,
    INVITE_REVOKED,
    ROLE_DIRECTOR,
    ROLE_FINANCE,
    ROLE_SITE_MANAGER,
)
from app.deps import get_token_claims
from app.main import app
from app.models.company import Company
from app.models.invite import Invite
from app.models.user import User


def _claims(sub: str, email: str | None = None):
    return lambda: {"sub": sub, "email": email}


@pytest.fixture(autouse=True)
def _no_email(monkeypatch):
    """Capture invite emails instead of hitting Resend."""
    from app.services.email_service import email_service

    sent = []
    monkeypatch.setattr(
        email_service,
        "send_user_invitation_email",
        lambda email, company_name, token: sent.append(
            {"email": email, "company": company_name, "token": token}
        )
        or {"sent": True, "id": "x"},
    )
    return sent


def _mk_invite(db, company, inviter, *, email="newhire@a.com", role=ROLE_FINANCE,
               token="tok-fixed", status=INVITE_PENDING, expires_in_days=7):
    inv = Invite(
        company_id=company.id,
        email=email,
        role=role,
        token=token,
        status=status,
        invited_by=inviter.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days),
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


# --- Create -----------------------------------------------------------------
def test_director_creates_invite(client, seed, db, _no_email):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    r = client.post("/api/v1/settings/invites", json={"email": "Yeni@Firma.com", "role": "finance"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["email"] == "yeni@firma.com"  # normalised
    assert data["role"] == "finance"
    assert data["status"] == "pending"

    row = db.execute(
        Invite.__table__.select().where(Invite.token == _no_email[0]["token"])
    ).first()
    assert row is not None
    assert _no_email[0]["email"] == "yeni@firma.com"
    # Token is opaque and non-trivial (secrets.token_urlsafe(32)).
    assert len(_no_email[0]["token"]) >= 32


def test_create_invite_requires_director(client, seed):
    client.login(seed["a"]["users"][ROLE_SITE_MANAGER])
    r = client.post("/api/v1/settings/invites", json={"email": "x@y.com", "role": "finance"})
    assert r.status_code == 403


def test_create_invite_rejects_existing_member(client, seed):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    member_email = seed["a"]["users"][ROLE_FINANCE].email
    client.login(director)
    r = client.post("/api/v1/settings/invites", json={"email": member_email, "role": "finance"})
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "Bu e-posta zaten kayıtlı"


def test_create_invite_dedups_pending(client, seed, db, _no_email):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    first = client.post("/api/v1/settings/invites", json={"email": "dup@a.com", "role": "finance"})
    second = client.post("/api/v1/settings/invites", json={"email": "dup@a.com", "role": "finance"})
    assert first.status_code == 200 and second.status_code == 200
    # Same token re-sent, not a second row.
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    rows = db.execute(
        Invite.__table__.select().where(Invite.email == "dup@a.com")
    ).fetchall()
    assert len(rows) == 1


# --- List / revoke ----------------------------------------------------------
def test_list_invites_scoped_to_company(client, seed, db):
    a_dir = seed["a"]["users"][ROLE_DIRECTOR]
    _mk_invite(db, seed["a"]["company"], a_dir, email="a-invite@a.com", token="tok-a")
    _mk_invite(db, seed["b"]["company"], seed["b"]["users"][ROLE_DIRECTOR],
               email="b-invite@b.com", token="tok-b")

    client.login(a_dir)
    r = client.get("/api/v1/settings/invites")
    assert r.status_code == 200, r.text
    emails = {i["email"] for i in r.json()["data"]}
    assert "a-invite@a.com" in emails
    assert "b-invite@b.com" not in emails  # other company's invite is invisible


def test_revoke_invite(client, seed, db):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    inv = _mk_invite(db, seed["a"]["company"], director, token="tok-rev")
    client.login(director)
    r = client.delete(f"/api/v1/settings/invites/{inv.id}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == INVITE_REVOKED
    db.refresh(inv)
    assert inv.status == INVITE_REVOKED


def test_revoke_other_company_invite_404(client, seed, db):
    # A director of company B cannot revoke company A's invite (app-layer scoping;
    # RLS is the DB backstop validated on real Postgres).
    a_inv = _mk_invite(db, seed["a"]["company"], seed["a"]["users"][ROLE_DIRECTOR], token="tok-a2")
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    r = client.delete(f"/api/v1/settings/invites/{a_inv.id}")
    assert r.status_code == 404


def test_cannot_revoke_accepted_invite(client, seed, db):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    inv = _mk_invite(db, seed["a"]["company"], director, token="tok-acc", status=INVITE_ACCEPTED)
    client.login(director)
    r = client.delete(f"/api/v1/settings/invites/{inv.id}")
    assert r.status_code == 422


# --- Public preview ---------------------------------------------------------
def test_get_invite_preview(client, seed, db):
    inv = _mk_invite(db, seed["a"]["company"], seed["a"]["users"][ROLE_DIRECTOR],
                     email="preview@a.com", role=ROLE_FINANCE, token="tok-prev")
    r = client.get(f"/api/v1/auth/invite/{inv.token}")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["company_name"] == seed["a"]["company"].name
    assert data["email"] == "preview@a.com"
    assert data["role"] == "finance"


def test_get_invite_unknown_404(client, seed):
    r = client.get("/api/v1/auth/invite/does-not-exist")
    assert r.status_code == 404


def test_get_invite_revoked_404(client, seed, db):
    inv = _mk_invite(db, seed["a"]["company"], seed["a"]["users"][ROLE_DIRECTOR],
                     token="tok-rev2", status=INVITE_REVOKED)
    r = client.get(f"/api/v1/auth/invite/{inv.token}")
    assert r.status_code == 404


# --- Accept -----------------------------------------------------------------
def test_accept_attaches_to_inviting_company(client, seed, db):
    company_a = seed["a"]["company"]
    inv = _mk_invite(db, company_a, seed["a"]["users"][ROLE_DIRECTOR],
                     email="joiner@a.com", role=ROLE_FINANCE, token="tok-join")
    new_sub = str(uuid.uuid4())
    app.dependency_overrides[get_token_claims] = _claims(new_sub, "joiner@a.com")
    try:
        r = client.post(f"/api/v1/auth/invite/{inv.token}/accept", json={"full_name": "Yeni Üye"})
    finally:
        app.dependency_overrides.pop(get_token_claims, None)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    # Joined the INVITING company, with the invited role — not a new company.
    assert data["company_id"] == str(company_a.id)
    assert data["role"] == "finance"
    assert data["id"] == new_sub

    user = db.get(User, uuid.UUID(new_sub))
    assert user is not None and user.company_id == company_a.id
    assert user.full_name == "Yeni Üye"
    db.refresh(inv)
    assert inv.status == INVITE_ACCEPTED and str(inv.accepted_by) == new_sub
    # No stray company was created (still exactly the two seeded companies).
    assert len(db.execute(Company.__table__.select()).fetchall()) == 2


def test_accept_without_jwt_email_uses_invite_email(client, seed, db):
    inv = _mk_invite(db, seed["a"]["company"], seed["a"]["users"][ROLE_DIRECTOR],
                     email="noemail@a.com", token="tok-noemail")
    sub = str(uuid.uuid4())
    app.dependency_overrides[get_token_claims] = _claims(sub, None)
    try:
        r = client.post(f"/api/v1/auth/invite/{inv.token}/accept", json={})
    finally:
        app.dependency_overrides.pop(get_token_claims, None)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["email"] == "noemail@a.com"


def test_accept_rejects_email_mismatch(client, seed, db):
    inv = _mk_invite(db, seed["a"]["company"], seed["a"]["users"][ROLE_DIRECTOR],
                     email="cfo@a.com", token="tok-mismatch")
    app.dependency_overrides[get_token_claims] = _claims(str(uuid.uuid4()), "attacker@evil.com")
    try:
        r = client.post(f"/api/v1/auth/invite/{inv.token}/accept", json={})
    finally:
        app.dependency_overrides.pop(get_token_claims, None)
    assert r.status_code == 403


def test_accept_rejects_existing_user(client, seed, db):
    # An auth id already attached to a company cannot accept another invite.
    existing = seed["b"]["users"][ROLE_FINANCE]
    inv = _mk_invite(db, seed["a"]["company"], seed["a"]["users"][ROLE_DIRECTOR],
                     email=existing.email, token="tok-existing")
    app.dependency_overrides[get_token_claims] = _claims(str(existing.id), existing.email)
    try:
        r = client.post(f"/api/v1/auth/invite/{inv.token}/accept", json={})
    finally:
        app.dependency_overrides.pop(get_token_claims, None)
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "Zaten bir şirkete kayıtlısınız"


def test_accept_rejects_expired_token(client, seed, db):
    inv = _mk_invite(db, seed["a"]["company"], seed["a"]["users"][ROLE_DIRECTOR],
                     email="late@a.com", token="tok-expired", expires_in_days=-1)
    app.dependency_overrides[get_token_claims] = _claims(str(uuid.uuid4()), "late@a.com")
    try:
        r = client.post(f"/api/v1/auth/invite/{inv.token}/accept", json={})
    finally:
        app.dependency_overrides.pop(get_token_claims, None)
    assert r.status_code == 404


def test_accept_rejects_revoked_token(client, seed, db):
    inv = _mk_invite(db, seed["a"]["company"], seed["a"]["users"][ROLE_DIRECTOR],
                     email="rev@a.com", token="tok-revoked", status=INVITE_REVOKED)
    app.dependency_overrides[get_token_claims] = _claims(str(uuid.uuid4()), "rev@a.com")
    try:
        r = client.post(f"/api/v1/auth/invite/{inv.token}/accept", json={})
    finally:
        app.dependency_overrides.pop(get_token_claims, None)
    assert r.status_code == 404


def test_token_is_single_use(client, seed, db):
    inv = _mk_invite(db, seed["a"]["company"], seed["a"]["users"][ROLE_DIRECTOR],
                     email="once@a.com", token="tok-once")
    app.dependency_overrides[get_token_claims] = _claims(str(uuid.uuid4()), "once@a.com")
    try:
        first = client.post(f"/api/v1/auth/invite/{inv.token}/accept", json={})
        # Second attempt (even by a fresh auth id) is rejected — token consumed.
        app.dependency_overrides[get_token_claims] = _claims(str(uuid.uuid4()), "once@a.com")
        second = client.post(f"/api/v1/auth/invite/{inv.token}/accept", json={})
    finally:
        app.dependency_overrides.pop(get_token_claims, None)
    assert first.status_code == 200, first.text
    assert second.status_code == 404
