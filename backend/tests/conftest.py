"""Pytest configuration & fixtures.

API/integration tests run against an in-memory SQLite database via the portable
column types (app/models/types.py), so no Postgres instance is required.
"""
import os
import sys
import uuid
from datetime import date

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app.constants import (
    ROLE_DIRECTOR,
    ROLE_FINANCE,
    ROLE_PROJECT_MANAGER,
    ROLE_SITE_MANAGER,
)
from app.deps import get_current_user
from app.db import get_db
from app.main import app
from app.models import Base, Company, Project, User


@pytest.fixture(autouse=True)
def _no_fx_network():
    """CR-014: never let a test hit the live TCMB feed. The FX service's
    cache-based walk-back over seeded fx_rates still works with live fetch off;
    tests that exercise the fetch boundary re-enable it explicitly."""
    from app.config import settings

    original = settings.fx_live_fetch
    settings.fx_live_fetch = False
    yield
    settings.fx_live_fetch = original


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture()
def db(session_factory):
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def seed(db):
    """Two isolated companies, each with a full set of role users + a project."""
    data = {}
    for label in ("a", "b"):
        # CR-004-N: the generic approval gates default On in production; the broad
        # test suite opts out so it exercises CRUD directly. CR-004-N tests flip
        # the relevant toggle back on for the trigger they cover.
        company = Company(
            name=f"Şirket {label.upper()}", slug=f"sirket-{label}",
            require_budget_approval=False, require_subcontractor_approval=False,
            require_deletion_approval=False, require_variation_approval=False,
        )
        db.add(company)
        db.flush()
        users = {}
        for role in (ROLE_DIRECTOR, ROLE_PROJECT_MANAGER, ROLE_FINANCE, ROLE_SITE_MANAGER):
            u = User(
                company_id=company.id,
                full_name=f"{role} {label}",
                email=f"{role}.{label}@example.com",
                role=role,
            )
            db.add(u)
            db.flush()
            users[role] = u
        project = Project(
            company_id=company.id,
            name=f"Proje {label}",
            project_code=f"PRJ-{label}",
            project_type="road",
            client_name="İşveren",
            contract_value_try=1_000_000,
            original_budget_try=800_000,
            start_date=date(2025, 1, 1),
            planned_end_date=date(2025, 12, 31),
            project_manager_id=users[ROLE_PROJECT_MANAGER].id,
        )
        db.add(project)
        db.flush()
        data[label] = {"company": company, "users": users, "project": project}
    db.commit()
    return data


@pytest.fixture()
def client(session_factory):
    """TestClient with DB + auth overridden. Use client.login(user) to authenticate."""
    from fastapi.testclient import TestClient

    db_module.set_sessionmaker(session_factory)

    # Reset the in-memory rate-limit window so tests don't accumulate hits across
    # the suite (the TestClient shares a single client IP).
    from app.middleware.rate_limit import reset_rate_limits
    from app.middleware.limits import reset_limits

    reset_rate_limits()
    reset_limits()

    holder: dict = {"user_id": None}

    def _override_get_db():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    def _override_current_user():
        from app.responses import APIError

        if holder["user_id"] is None:
            raise APIError(401, "UNAUTHENTICATED", "Kimlik doğrulama gerekli")
        s = session_factory()
        try:
            user = s.get(User, holder["user_id"])
            if user is None:
                raise APIError(401, "UNAUTHENTICATED", "Kullanıcı bulunamadı")
            s.expunge(user)
            return user
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_current_user

    c = TestClient(app)

    def login(user: User | None):
        holder["user_id"] = user.id if user else None

    c.login = login  # type: ignore[attr-defined]
    yield c
    app.dependency_overrides.clear()
