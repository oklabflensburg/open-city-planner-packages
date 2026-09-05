"""Real PostgreSQL tests: each test owns a randomly named, disposable schema."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from web.backend.app.db.config import database_url

ROOT = Path(__file__).resolve().parents[3]


def migration_config(connection):
    config = Config(str(ROOT / "web/backend/alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def pg_engine():
    raw = os.environ.get("PACKAGES_REGISTRY_TEST_DATABASE_URL")
    if not raw:
        pytest.fail("Set PACKAGES_REGISTRY_TEST_DATABASE_URL to a disposable PostgreSQL database")
    url = database_url(raw)
    admin = create_engine(url, hide_parameters=True)
    schema = f"registry_test_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000"},
    )
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "head")
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
