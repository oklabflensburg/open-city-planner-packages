"""Explicit PostgreSQL configuration without import-time connections."""

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url


def database_url(value: str | None = None) -> URL:
    raw = value if value is not None else os.environ.get("PACKAGES_REGISTRY_DATABASE_URL")
    if not raw:
        raise ValueError("PACKAGES_REGISTRY_DATABASE_URL is required for shadow DB operations")
    try:
        url = make_url(raw)
    except Exception:
        raise ValueError("Invalid Registry database URL") from None
    if url.drivername != "postgresql+psycopg" or not url.database:
        raise ValueError("Registry database URL must use postgresql+psycopg and name a database")
    return url


def database_engine(value: str | None = None) -> Engine:
    return create_engine(database_url(value), pool_pre_ping=True, hide_parameters=True)
