"""Registration / auto-provisioning tests (Section 3.3)."""
import uuid

from app.deps import get_token_claims
from app.main import app
from app.models.company import Company
from app.models.user import User


def _claims(sub: str, email: str = "new.director@example.com"):
    return lambda: {"sub": sub, "email": email}


def test_register_provisions_company_and_director(client, db):
    sub = str(uuid.uuid4())
    app.dependency_overrides[get_token_claims] = _claims(sub)
    r = client.post(
        "/api/v1/auth/register",
        json={"company_name": "Test Şirketi", "full_name": "Mertcan Doğan"},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["role"] == "director"
    assert data["email"] == "new.director@example.com"
    assert data["id"] == sub

    # Company + user actually persisted.
    user = db.get(User, uuid.UUID(sub))
    assert user is not None
    company = db.get(Company, user.company_id)
    assert company.name == "Test Şirketi"
    assert company.subscription_status == "trial"


def test_register_is_idempotent(client):
    sub = str(uuid.uuid4())
    app.dependency_overrides[get_token_claims] = _claims(sub, "dupe@example.com")
    first = client.post("/api/v1/auth/register", json={"company_name": "A", "full_name": "X"})
    second = client.post("/api/v1/auth/register", json={"company_name": "B", "full_name": "Y"})
    assert first.status_code == 200 and second.status_code == 200
    # Same user row returned; not duplicated.
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert second.json()["data"]["email"] == "dupe@example.com"


def test_register_rejects_email_already_used_by_other_auth_id(client, seed):
    existing_email = seed["a"]["users"]["director"].email
    app.dependency_overrides[get_token_claims] = _claims(str(uuid.uuid4()), existing_email)
    r = client.post("/api/v1/auth/register", json={"company_name": "C", "full_name": "Z"})
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "Bu e-posta zaten kayıtlı"


def test_register_unique_company_slug(client):
    # Two different auth users registering the same company name → distinct slugs.
    sub1, sub2 = str(uuid.uuid4()), str(uuid.uuid4())
    app.dependency_overrides[get_token_claims] = _claims(sub1, "a1@example.com")
    client.post("/api/v1/auth/register", json={"company_name": "Aynı İsim", "full_name": "A"})
    app.dependency_overrides[get_token_claims] = _claims(sub2, "a2@example.com")
    r = client.post("/api/v1/auth/register", json={"company_name": "Aynı İsim", "full_name": "B"})
    assert r.status_code == 200, r.text
