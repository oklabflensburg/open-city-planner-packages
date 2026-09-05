"""Migration environment for the optional shadow database."""

from alembic import context

from web.backend.app.db.config import database_engine, database_url
from web.backend.app.db.models import Base


def run_migrations() -> None:
    if context.is_offline_mode():
        context.configure(url=database_url(), target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    # Tests can supply an isolated PostgreSQL connection without global env changes.
    connection = context.config.attributes.get("connection")
    if connection is not None:
        migrate(connection)
        return
    engine = database_engine()
    try:
        with engine.connect() as connection:
            migrate(connection)
    finally:
        engine.dispose()


def migrate(connection: object) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
