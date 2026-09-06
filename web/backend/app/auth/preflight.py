"""Read-only production gate, invoked with a root-owned systemd EnvironmentFile."""

import argparse
import asyncio
import os

from sqlalchemy import create_engine, text

from web.backend.app.auth.config import get_settings
from web.backend.app.auth.models.base import Base
from web.backend.app.auth.redis import get_redis
from web.backend.app.db.config import database_url
from web.backend.app.db.models import Base as RegistryBase


def check_database(settings):
    engine = create_engine(
        database_url(settings.auth_database_url),
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            if (
                connection.scalar(text("SELECT version_num FROM auth_alembic_version"))
                != "0063_auth_persistence"
            ):
                raise RuntimeError("Auth migration required")
            for table in Base.metadata.tables:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    allowed = connection.scalar(
                        text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                        {"table": table, "privilege": privilege},
                    )
                    if not allowed:
                        raise RuntimeError("Auth database role lacks required table grants")
            for table in RegistryBase.metadata.tables:
                # Search all schemas: auth's search_path must not hide Registry write grants.
                rows = connection.execute(
                    text(
                        "SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE c.relname=:table AND c.relkind='r'"
                    ),
                    {"table": table},
                )
                for (oid,) in rows:
                    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "TRIGGER"):
                        if connection.scalar(
                            text("SELECT has_table_privilege(current_user, :oid, :privilege)"),
                            {"oid": oid, "privilege": privilege},
                        ):
                            raise RuntimeError("Auth database role must not write Registry tables")
    finally:
        engine.dispose()


async def check_limiter():
    client = get_redis()
    if client is None:
        raise RuntimeError("Security rate limiter missing")
    try:
        await client.ping()
    finally:
        await client.aclose()
        get_redis.cache_clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-origin", required=True)
    arguments = parser.parse_args()
    stage = "configuration"
    try:
        settings = get_settings()
        if not settings.production or os.environ.get("AUTH_ENABLED", "").lower() != "true":
            raise RuntimeError("Production activation settings required")
        if settings.app_base_url.rstrip("/") != arguments.expected_origin.rstrip("/"):
            raise RuntimeError("Auth origin does not match the Package Hub")
        if settings.webauthn_origin.rstrip("/") != arguments.expected_origin.rstrip("/"):
            raise RuntimeError("WebAuthn origin does not match the Package Hub")
        stage = "database schema and grants"
        check_database(settings)
        stage = "security rate limiter"
        asyncio.run(check_limiter())
    except Exception:
        # Validation/driver exceptions can contain input values. Never print them.
        print(f"Auth production preflight failed at {stage}; no data was changed.")
        return 1
    print("Auth production preflight passed; no data was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
