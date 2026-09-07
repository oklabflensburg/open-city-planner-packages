"""Explicit auth connection, separate from the read-only Registry role."""

from fastapi import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from web.backend.app.auth.config import get_settings
from web.backend.app.auth.db_config import auth_database_url


def configure_database(application):
    settings = get_settings()
    if not settings.auth_database_url:
        raise ValueError("AUTH_DATABASE_URL is required when authentication is enabled")
    url = auth_database_url(settings.auth_database_url)
    engine = create_async_engine(
        url,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        # PostgreSQL is local; avoid default SSL key discovery under ProtectHome.
        connect_args={
            "timeout": 5,
            "ssl": False,
            "server_settings": {"statement_timeout": "10000"},
        },
    )
    application.state.auth_engine = engine
    application.state.auth_sessions = async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request):
    async with request.app.state.auth_sessions() as session:
        yield session
