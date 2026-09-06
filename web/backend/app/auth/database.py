"""Explicit auth connection, separate from the read-only Registry role."""

from fastapi import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from web.backend.app.auth.config import get_settings
from web.backend.app.db.config import database_url


def configure_database(application):
    settings = get_settings()
    if not settings.auth_database_url:
        raise ValueError("AUTH_DATABASE_URL is required when authentication is enabled")
    url = database_url(settings.auth_database_url)
    options = str(url.query.get("options", "")) + " -cstatement_timeout=10000"
    engine = create_async_engine(
        url,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        connect_args={"connect_timeout": 5, "options": options},
    )
    application.state.auth_engine = engine
    application.state.auth_sessions = async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request):
    async with request.app.state.auth_sessions() as session:
        yield session
