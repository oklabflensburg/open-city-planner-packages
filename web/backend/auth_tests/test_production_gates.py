import logging
import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from web.backend.app.auth.config import Settings
from web.backend.app.auth.logging import AuthAccessFilter
from web.backend.app.auth.models.base import Base
from web.backend.app.auth.preflight import check_database


def production(**override):
    values = dict(
        app_environment="production",
        jwt_secret_key=secrets.token_urlsafe(48),
        oauth_state_secret=secrets.token_urlsafe(48),
        mfa_recovery_pepper=secrets.token_urlsafe(48),
        mfa_encryption_key=Fernet.generate_key().decode(),
        auth_cookie_secure=True,
        refresh_require_origin=True,
        auth_rate_limit_backend="redis",
        redis_enabled=True,
        rate_limit_fail_closed=True,
        app_base_url="https://packages.example.org",
        api_base_url="https://packages.example.org",
        jwt_issuer="https://packages.example.org",
        webauthn_origin="https://packages.example.org",
        webauthn_rp_id="packages.example.org",
        email_backend="smtp",
        smtp_host="smtp.example.org",
    )
    values.update(override)
    return Settings(**values)


@pytest.mark.parametrize(
    "override",
    [
        {"jwt_secret_key": "NOT_A_SECRET"},
        {"auth_cookie_secure": False},
        {"refresh_require_origin": False},
        {"auth_rate_limit_backend": "memory"},
        {"rate_limit_fail_closed": False},
        {"redis_enabled": False},
        {"mfa_encryption_key": None},
        {"email_backend": "console"},
        {"smtp_use_tls": False},
        {"app_base_url": "http://packages.example.org"},
        {"webauthn_rp_id": "other.example.org"},
        {"webauthn_origin": "https://evil.test"},
        {"oauth_redirect_base_url": "https://evil.test/path"},
        {"github_client_id": "test-client"},
        {"auth_cookie_samesite": "none"},
    ],
)
def test_unsafe_production_config_rejected(override):
    with pytest.raises(RuntimeError):
        production(**override).validate_security()


def test_valid_config_and_secret_separation():
    settings = production()
    settings.validate_security()
    assert settings.jwt_secret_key not in repr(settings)
    assert settings.mfa_encryption_key not in repr(settings)
    settings.oauth_state_secret = settings.jwt_secret_key
    with pytest.raises(RuntimeError, match="distinct"):
        settings.validate_security()


def test_auth_access_log_removes_query_but_registry_logging_unchanged():
    args = (
        "peer",
        "GET",
        "/api/v1/auth/oauth/github/callback?code=NOT_A_SECRET_TEST_SENTINEL",
        "1.1",
        302,
    )
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s %s %s %s", args, None)
    AuthAccessFilter().filter(record)
    assert "NOT_A_SECRET" not in record.getMessage()
    args = ("peer", "GET", "/api/v1/search?q=statistics", "1.1", 200)
    record.args = args
    AuthAccessFilter().filter(record)
    assert record.args == args


def test_read_only_preflight_requires_auth_grants_and_rejects_registry_writes(auth_engine):
    role = f"auth_gate_{uuid4().hex}"
    with auth_engine.begin() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
        connection.exec_driver_sql(f'CREATE ROLE "{role}"')
        connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        for table in Base.metadata.tables:
            connection.exec_driver_sql(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO "{role}"'
            )
        connection.exec_driver_sql(f'GRANT SELECT ON auth_alembic_version TO "{role}"')
    url = auth_engine.url.update_query_dict({"options": f"-csearch_path={schema} -crole={role}"})
    settings = SimpleNamespace(auth_database_url=url.render_as_string(hide_password=False))
    try:
        check_database(settings)
        with auth_engine.begin() as connection:
            connection.exec_driver_sql(f'GRANT INSERT ON modules TO "{role}"')
        with pytest.raises(RuntimeError, match="must not write Registry"):
            check_database(settings)
    finally:
        with auth_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP OWNED BY "{role}"')
            connection.exec_driver_sql(f'DROP ROLE "{role}"')


@pytest.mark.asyncio
async def test_limiter_failure_is_closed_without_memory_fallback(monkeypatch):
    from web.backend.app.auth.services import rate_limit

    settings = production()
    monkeypatch.setattr(rate_limit, "get_settings", lambda: settings)
    monkeypatch.setattr(rate_limit, "get_redis", lambda: None)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await rate_limit.check_rate_limit("test")
    assert raised.value.status_code == 503
    assert raised.value.detail["error"]["code"] == "RATE_LIMIT_UNAVAILABLE"
