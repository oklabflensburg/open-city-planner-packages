"""Auth rate limiting uses an explicitly configured Redis service."""

from functools import lru_cache

from redis.asyncio import Redis

from web.backend.app.auth.config import get_settings


@lru_cache
def get_redis():
    settings = get_settings()
    if not settings.redis_enabled:
        return None
    return Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.redis_connect_timeout,
        socket_timeout=settings.redis_socket_timeout,
        max_connections=settings.redis_max_connections,
    )
