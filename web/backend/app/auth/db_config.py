"""One asyncpg auth URL; derive psycopg only for synchronous maintenance."""

import os

from sqlalchemy.engine import URL, make_url


def auth_database_url(value: str | None = None) -> URL:
    raw = value if value is not None else os.environ.get("AUTH_DATABASE_URL")
    if not raw:
        raise ValueError("AUTH_DATABASE_URL is required for auth database operations")
    try:
        url = make_url(raw)
    except Exception:
        # SQLAlchemy parse errors may include the input, including credentials.
        raise ValueError("Invalid auth database URL") from None
    if url.drivername != "postgresql+asyncpg" or not url.database:
        raise ValueError("Auth database URL must use postgresql+asyncpg and name a database")
    return url


def auth_sync_database_url(value: str | None = None) -> URL:
    return auth_database_url(value).set(drivername="postgresql+psycopg")
