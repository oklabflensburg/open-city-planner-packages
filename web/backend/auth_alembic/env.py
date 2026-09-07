"""Auth-only migrations; the Registry Alembic history remains untouched."""

import os

from alembic import context
from sqlalchemy import create_engine

from web.backend.app.auth import models  # noqa: F401
from web.backend.app.auth.db_config import auth_sync_database_url
from web.backend.app.auth.models.base import Base


def include_object(obj, name, type_, reflected, compare_to):
    return type_ != "table" or name in Base.metadata.tables


def migrate(connection):
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        version_table="auth_alembic_version",
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations():
    connection = context.config.attributes.get("connection")
    if connection is not None:
        migrate(connection)
        return
    raw = os.environ.get("AUTH_DATABASE_URL")
    if not raw:
        raise ValueError("AUTH_DATABASE_URL is required for auth migrations")
    url = auth_sync_database_url(raw)
    if context.is_offline_mode():
        context.configure(
            url=url,
            target_metadata=Base.metadata,
            literal_binds=True,
            version_table="auth_alembic_version",
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            migrate(connection)
    finally:
        engine.dispose()


run_migrations()
