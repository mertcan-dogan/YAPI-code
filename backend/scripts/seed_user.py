"""One-time seeder: create a company + a public.users row for an existing
Supabase Auth user.

Use this when a user already exists in Supabase Auth (auth.users) but has no
matching row in public.users, which makes /auth/me return 401.

Run from the backend/ directory with .env populated (DATABASE_URL must point at
the project Postgres — the service/direct connection, which bypasses RLS):

    python scripts/seed_user.py \
        --user-id 7910xxxx-70eb-4202-96d9-c10f2b68c59f \
        --email 99.mertcan.dogan@gmail.com \
        --name "Mertcan Doğan" \
        --company "Test Şirketi" \
        --role director

Defaults are filled for the test user; --user-id is validated as a real UUID.
The script is idempotent — re-running it updates the existing rows.
"""
import argparse
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Windows consoles default to cp1252 and choke on Turkish/Unicode output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

from slugify import slugify
from sqlalchemy import select

from app.constants import ROLES, ROLE_DIRECTOR
from app.db import SessionLocal
from app.models.company import Company
from app.models.user import User


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed a company + public.users row.")
    p.add_argument("--user-id", default=os.getenv("SEED_USER_ID", ""),
                   help="Supabase auth user id (the token 'sub' — a UUID).")
    p.add_argument("--email", default=os.getenv("SEED_EMAIL", "99.mertcan.dogan@gmail.com"))
    p.add_argument("--name", default=os.getenv("SEED_NAME", ""))
    p.add_argument("--company", default=os.getenv("SEED_COMPANY", "Test Şirketi"))
    p.add_argument("--role", default=os.getenv("SEED_ROLE", ROLE_DIRECTOR), choices=ROLES)
    return p.parse_args()


def _valid_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        print(
            f"\n[ERROR] '{value}' is not a valid UUID.\n"
            "   The Supabase auth user id (token 'sub') is a hex UUID — note it\n"
            "   contains only 0-9 and a-f (no letter 'l', 'o', etc.). Copy the\n"
            "   exact value from Supabase → Authentication → Users, or from the\n"
            "   diagnostic output, and pass it via --user-id.\n"
        )
        sys.exit(2)


def main() -> None:
    args = _parse_args()
    if not args.user_id:
        print("[ERROR] --user-id is required (or set SEED_USER_ID).")
        sys.exit(2)
    uid = _valid_uuid(args.user_id)
    full_name = args.name or args.email.split("@")[0]

    db = SessionLocal()
    try:
        # 1) Company (idempotent by slug).
        slug = slugify(args.company)[:100] or "test-sirketi"
        company = db.execute(select(Company).where(Company.slug == slug)).scalar_one_or_none()
        if company is None:
            company = Company(
                name=args.company,
                slug=slug,
                default_currency="TRY",
                subscription_status="trial",
                trial_ends_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
            db.add(company)
            db.flush()
            print(f"[OK] Created company '{company.name}' (id={company.id})")
        else:
            print(f"[INFO]  Company '{company.name}' already exists (id={company.id})")

        # 2) User row (idempotent by id, then email).
        user = db.get(User, uid)
        if user is None:
            user = db.execute(select(User).where(User.email == args.email)).scalar_one_or_none()

        if user is None:
            user = User(
                id=uid,
                company_id=company.id,
                full_name=full_name,
                email=args.email,
                role=args.role,
                preferred_language="tr",
                is_active=True,
            )
            db.add(user)
            print(f"[OK] Created user '{user.email}' (id={uid}, role={args.role})")
        else:
            user.company_id = company.id
            user.role = args.role
            user.is_active = True
            if not user.full_name:
                user.full_name = full_name
            print(f"[INFO]  Updated existing user '{user.email}' → company={company.id}, role={args.role}")

        db.commit()
        print("\n[DONE] Done. Sign in again — /auth/me should now return your profile.")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"\n[ERROR] Seeding failed: {type(exc).__name__}: {exc}")
        print("   If this is an RLS/permission error, run with a DATABASE_URL that uses")
        print("   the project's direct/service Postgres connection (it bypasses RLS).")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
