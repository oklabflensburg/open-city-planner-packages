"""Opt-in auth integration; no migrations or Registry write grants at startup."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from web.backend.app.auth.api import router
from web.backend.app.auth.config import get_settings
from web.backend.app.auth.database import configure_database
from web.backend.app.auth.oauth_api import router as oauth_router
from web.backend.app.auth.redis import get_redis
from web.backend.app.auth.users_api import router as users_router


def configure_auth(application: FastAPI):
    settings = get_settings()
    configure_database(application)
    original_lifespan = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with original_lifespan(app):
                yield
        finally:
            await app.state.auth_engine.dispose()
            client = get_redis()
            if client is not None:
                await client.aclose()
            get_redis.cache_clear()

    application.router.lifespan_context = lifespan
    application.include_router(router, prefix="/api/v1")
    application.include_router(oauth_router, prefix="/api/v1")
    application.include_router(users_router, prefix="/api/v1")

    @application.middleware("http")
    async def private_auth_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/api/v1/auth", "/api/v1/users")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @application.get("/health/auth", tags=["health"])
    async def auth_readiness():
        try:
            async with application.state.auth_engine.connect() as connection:
                revision = await connection.scalar(
                    text("SELECT version_num FROM auth_alembic_version")
                )
            if revision != "0063_auth_persistence":
                raise ValueError("Unsupported auth schema")
            if settings.auth_rate_limit_backend == "redis":
                client = get_redis()
                if client is None or not await client.ping():
                    raise ValueError("Rate limiter unavailable")
        except (SQLAlchemyError, OSError, ValueError):
            return JSONResponse(
                {"status": "unavailable"}, status_code=503, headers={"Cache-Control": "no-store"}
            )
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})
