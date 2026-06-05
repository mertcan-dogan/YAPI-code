"""Portable column types.

Production runs on PostgreSQL (UUID, JSONB, INET). To allow the test suite to
run on SQLite without a Postgres instance, these TypeDecorators map to the
native Postgres types on Postgres and to portable fallbacks elsewhere. The
public names mirror the Postgres ones so model code reads naturally.
"""
import uuid

from sqlalchemy.dialects.postgresql import INET as PG_INET
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import CHAR, JSON, String, TypeDecorator


class GUID(TypeDecorator):
    """UUID on Postgres, CHAR(36) elsewhere. Always yields uuid.UUID on read."""

    impl = CHAR
    cache_ok = True

    def __init__(self, *args, **kwargs):  # accept/ignore as_uuid=True
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


# JSONB on Postgres, generic JSON elsewhere.
JSONB = JSON().with_variant(PG_JSONB(), "postgresql")

# INET on Postgres, plain string elsewhere.
INET = String(64).with_variant(PG_INET(), "postgresql")

# Alias so existing imports `UUID as PGUUID` keep working.
PGUUID = GUID
