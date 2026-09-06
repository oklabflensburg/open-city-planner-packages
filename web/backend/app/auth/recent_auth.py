# Adapted from open-city-planner 2238e18 (AGPL-3.0-only).
from fastapi import Request, status

from web.backend.app.auth.config import get_settings
from web.backend.app.auth.jwt import decode_jwt
from web.backend.app.auth.services.auth_service import auth_error, utcnow


def require_recent_auth(request: Request) -> None:
    settings = get_settings()
    token = request.cookies.get(settings.auth_access_cookie_name)
    try:
        payload = decode_jwt(token or "", "access")
        auth_time = payload.get("auth_time")
    except Exception as exc:
        raise auth_error(
            "MFA_REAUTH_REQUIRED",
            "Bitte melden Sie sich erneut an, um fortzufahren.",
            status.HTTP_401_UNAUTHORIZED,
        ) from exc
    if (
        not isinstance(auth_time, int)
        or int(utcnow().timestamp()) - auth_time > settings.reauth_max_age_seconds
    ):
        raise auth_error(
            "MFA_REAUTH_REQUIRED",
            "Bitte melden Sie sich erneut an, um fortzufahren.",
            status.HTTP_401_UNAUTHORIZED,
        )
