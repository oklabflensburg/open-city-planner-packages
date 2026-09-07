"""Auth driver contract and real asyncpg runtime / synchronous migration paths."""

import os
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from asyncpg import connect_utils
from sqlalchemy import create_engine, event, text

from web.backend.app.auth.config import get_settings
from web.backend.app.auth.database import configure_database
from web.backend.app.auth.db_config import auth_database_url, auth_sync_database_url
from web.backend.db_tests.conftest import ROOT


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "invalid_SECRET_SENTINEL",
        "postgresql+asyncpg://user:SECRET_SENTINEL@host:notaport/db",
        "postgresql+psycopg://user:SECRET_SENTINEL@host/db",
        "postgresql://user:SECRET_SENTINEL@host/db",
        "sqlite:///db",
        "postgresql+asyncpg://user:SECRET_SENTINEL@host",
    ],
)
def test_invalid_runtime_urls_fail_without_credentials(raw):
    with pytest.raises(ValueError) as error:
        auth_database_url(raw)
    assert "SECRET_SENTINEL" not in str(error.value)
    assert "Registry database URL" not in str(error.value)
    assert error.value.__suppress_context__ or "must use" in str(error.value) or not raw


def test_one_environment_variable_and_no_registry_fallback(monkeypatch):
    monkeypatch.delenv("AUTH_DATABASE_URL", raising=False)
    monkeypatch.setenv("PACKAGES_REGISTRY_DATABASE_URL", "postgresql+psycopg://registry@host/db")
    with pytest.raises(ValueError, match="AUTH_DATABASE_URL is required"):
        auth_database_url()
    raw = "postgresql+asyncpg://user:pass@127.0.0.1:5432/db"
    monkeypatch.setenv("AUTH_DATABASE_URL", raw)
    assert auth_database_url().render_as_string(hide_password=False) == raw
    assert auth_sync_database_url().drivername == "postgresql+psycopg"


def test_sync_derivation_preserves_encoded_credentials_and_query():
    raw = "postgresql+asyncpg://user:p%40ss@host:5432/db?ssl=require"
    runtime, sync = auth_database_url(raw), auth_sync_database_url(raw)
    assert sync.render_as_string(hide_password=False) == (
        "postgresql+psycopg://user:p%40ss@host:5432/db?ssl=require"
    )
    for field in ("username", "password", "host", "port", "database", "query"):
        assert getattr(sync, field) == getattr(runtime, field)
    assert runtime.drivername == "postgresql+asyncpg"


@pytest.fixture
def empty_auth_database(pg_engine):
    """A separate empty DB exercises Alembic's environment path without injected connections."""
    name = f"auth_driver_{uuid4().hex}"
    admin = create_engine(pg_engine.url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    url = pg_engine.url.set(drivername="postgresql+asyncpg", database=name)
    try:
        yield url
    finally:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


@pytest.mark.asyncio
async def test_actual_runtime_engine_sessions_and_statement_timeout(
    empty_auth_database, monkeypatch
):
    monkeypatch.setenv(
        "AUTH_DATABASE_URL", empty_auth_database.render_as_string(hide_password=False)
    )
    get_settings.cache_clear()
    app = SimpleNamespace(state=SimpleNamespace())
    configure_database(app)
    engine = app.state.auth_engine
    connect_parameters = []

    def deny_postgresql_home_files(filename):
        raise PermissionError(f"ProtectHome denies ~/.postgresql/{filename}")

    # Keep the actual asyncpg connection path; only emulate the inaccessible
    # default SSL files of the hardened systemd service.
    monkeypatch.setattr(connect_utils, "_dot_postgresql_path", deny_postgresql_home_files)

    @event.listens_for(engine.sync_engine, "do_connect")
    def capture_connection_parameters(dialect, record, args, kwargs):
        connect_parameters.append(kwargs.copy())

    try:
        assert engine.dialect.driver == "asyncpg"
        assert engine.pool.size() == 5
        assert engine.pool.timeout() == 10
        assert engine.pool._max_overflow == 5
        assert engine.pool._pre_ping is True
        assert engine.sync_engine.hide_parameters is True
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
            assert await connection.scalar(text("SHOW statement_timeout")) == "10s"
        assert connect_parameters
        for parameters in connect_parameters:
            assert parameters["ssl"] is False
            assert parameters["timeout"] == 5
            assert parameters["server_settings"] == {"statement_timeout": "10000"}
        async with app.state.auth_sessions() as session:
            assert await session.scalar(text("SELECT 1")) == 1
            assert await session.scalar(text("SHOW statement_timeout")) == "10s"
    finally:
        await engine.dispose()


def test_alembic_migrates_empty_database_using_runtime_url(empty_auth_database):
    raw = empty_auth_database.render_as_string(hide_password=False)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "web/backend/auth_alembic.ini", "upgrade", "head"],
        cwd=ROOT,
        env=dict(os.environ, AUTH_DATABASE_URL=raw),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert raw not in result.stdout + result.stderr
    engine = create_engine(auth_sync_database_url(raw), hide_parameters=True)
    try:
        assert engine.dialect.driver == "psycopg"
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM auth_alembic_version")) == (
                "0063_auth_persistence"
            )
    finally:
        engine.dispose()
