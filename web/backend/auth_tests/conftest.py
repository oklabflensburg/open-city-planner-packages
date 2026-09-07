"""Auth tests use disposable PostgreSQL and a memory-only email transport."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from web.backend.app.auth.config import get_settings
from web.backend.app.auth.services import auth_service
from web.backend.app.auth.services.rate_limit import reset_memory_rate_limits
from web.backend.app.main import create_app
from web.backend.db_tests.conftest import pg_engine  # noqa: F401
from web.backend.db_tests.test_auth_persistence import auth_engine  # noqa: F401


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    get_settings.cache_clear()
    reset_memory_rate_limits()
    yield
    get_settings.cache_clear()
    reset_memory_rate_limits()


@pytest.fixture
def sent_mail(monkeypatch):
    verification, reset = AsyncMock(), AsyncMock()
    monkeypatch.setattr(auth_service, "send_verification_email", verification)
    monkeypatch.setattr(auth_service, "send_password_reset_email", reset)
    monkeypatch.setattr(auth_service, "send_password_changed_email", AsyncMock())
    return verification, reset


@pytest.fixture
def auth_client(auth_engine, monkeypatch, sent_mail):  # noqa: F811 - pytest fixture injection
    url = auth_engine.url.set(drivername="postgresql+asyncpg")
    monkeypatch.setenv("AUTH_DATABASE_URL", url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    app = create_app(auth_enabled=True)
    # Preserve schema isolation on async connections used by the actual API.
    with auth_engine.connect() as connection:
        schema = connection.exec_driver_sql("SELECT current_schema()").scalar_one()
    engine = create_async_engine(
        url,
        hide_parameters=True,
        connect_args={"server_settings": {"search_path": schema, "statement_timeout": "10000"}},
    )
    app.state.auth_engine = engine
    app.state.auth_sessions = async_sessionmaker(engine, expire_on_commit=False)
    with TestClient(app) as client:
        yield client
