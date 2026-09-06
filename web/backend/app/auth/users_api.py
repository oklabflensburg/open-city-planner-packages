# Adapted from open-city-planner 2238e18 (AGPL-3.0-only).
import uuid
from datetime import UTC, datetime

# Adapted from open-city-planner 2238e18 (AGPL-3.0-only).
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Request, Response

from web.backend.app.auth.config import get_settings
from web.backend.app.auth.csrf import validate_csrf
from web.backend.app.auth.dependencies import SessionDep, get_current_active_user
from web.backend.app.auth.jwt import decode_jwt
from web.backend.app.auth.models.user import User
from web.backend.app.auth.recent_auth import require_recent_auth
from web.backend.app.auth.schemas.auth import MessageResponse, PasskeyRead, PasskeyRenameRequest
from web.backend.app.auth.schemas.oauth import UserOAuthAccountRead
from web.backend.app.auth.schemas.user import AccountDeletionRequest, UserRead, UserUpdate
from web.backend.app.auth.services.account_service import deactivate_own_account, delete_own_account
from web.backend.app.auth.services.auth_service import clear_auth_cookies
from web.backend.app.auth.services.email_service import send_mfa_security_email
from web.backend.app.auth.services.oauth_account_service import (
    get_for_user,
    normalize_provider,
    unlink_oauth_account,
)
from web.backend.app.auth.services.passkey_service import (
    list_passkeys,
    remove_passkey,
    rename_passkey,
)

router = APIRouter(prefix="/users", tags=["account"])


@router.get("/me", response_model=UserRead)
async def get_user_me(user: Annotated[User, Depends(get_current_active_user)]) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/me", response_model=UserRead)
async def patch_user_me(
    payload: UserUpdate,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    validate_csrf(request)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(user, key, value)
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.get("/me/oauth-accounts", response_model=list[UserOAuthAccountRead])
async def get_user_oauth_accounts(
    session: SessionDep, user: Annotated[User, Depends(get_current_active_user)]
) -> list[UserOAuthAccountRead]:
    return [
        UserOAuthAccountRead.model_validate(account)
        for account in await get_for_user(session, user.id)
    ]


@router.delete("/me/oauth-accounts/{provider}", status_code=204)
async def delete_user_oauth_account(
    provider: str,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    validate_csrf(request)
    require_recent_auth(request)
    await unlink_oauth_account(session, user, normalize_provider(provider))


# Adapted from open-city-planner 2238e18 (AGPL-3.0-only).
def _access_authenticated_at(request: Request) -> datetime | None:
    token = request.cookies.get(get_settings().auth_access_cookie_name)
    if not token:
        return None
    try:
        authenticated_at = decode_jwt(token, "access").get("auth_time")
        return datetime.fromtimestamp(int(authenticated_at), UTC)
    except (jwt.PyJWTError, TypeError, ValueError, OverflowError):
        return None


@router.get("/me/passkeys", response_model=list[PasskeyRead])
async def get_user_passkeys(
    session: SessionDep, user: Annotated[User, Depends(get_current_active_user)]
) -> list[PasskeyRead]:
    return [PasskeyRead.model_validate(value) for value in await list_passkeys(session, user.id)]


@router.patch("/me/passkeys/{credential_id}", response_model=PasskeyRead)
async def patch_user_passkey(
    credential_id: uuid.UUID,
    payload: PasskeyRenameRequest,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> PasskeyRead:
    validate_csrf(request)
    require_recent_auth(request)
    record = await rename_passkey(session, user.id, credential_id, payload.name)
    return PasskeyRead.model_validate(record)


@router.delete("/me/passkeys/{credential_id}", status_code=204)
async def delete_user_passkey(
    credential_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    validate_csrf(request)
    require_recent_auth(request)
    remaining = await remove_passkey(session, user, credential_id)
    await send_mfa_security_email(
        session, user, "passkey_removed" if remaining else "passkeys_removed"
    )


@router.post(
    "/me/deactivate",
    response_model=MessageResponse,
    summary="Eigenes Benutzerkonto deaktivieren",
    responses={
        401: {"description": "Anmeldung erforderlich"},
        409: {"description": ("Das letzte aktive Superuser-Konto kann nicht deaktiviert werden")},
    },
)
async def post_deactivate_user_me(
    session: SessionDep,
    response: Response,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> MessageResponse:
    validate_csrf(request)
    await deactivate_own_account(session, user.id)
    clear_auth_cookies(response)
    return MessageResponse(message="Das Konto wurde deaktiviert.")


@router.delete(
    "/me",
    response_model=MessageResponse,
    summary="Eigenes Benutzerkonto dauerhaft löschen",
    responses={
        401: {"description": "Anmeldung erforderlich"},
        403: {"description": "Passwort oder kürzlich erfolgte Anmeldung erforderlich"},
        409: {"description": ("Das letzte aktive Superuser-Konto kann nicht gelöscht werden")},
    },
)
async def delete_user_me(
    payload: AccountDeletionRequest,
    session: SessionDep,
    response: Response,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> MessageResponse:
    validate_csrf(request)
    settings = get_settings()
    await delete_own_account(
        session,
        user.id,
        confirmation_text=payload.confirmation_text,
        current_password=payload.current_password,
        authenticated_at=_access_authenticated_at(request),
        recent_auth_seconds=settings.account_deletion_recent_auth_seconds,
    )
    clear_auth_cookies(response)
    return MessageResponse(message="Das Konto wurde dauerhaft gelöscht.")
