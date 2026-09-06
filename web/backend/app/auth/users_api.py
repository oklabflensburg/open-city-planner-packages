# Adapted from open-city-planner 2238e18 (AGPL-3.0-only).
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from web.backend.app.auth.csrf import validate_csrf
from web.backend.app.auth.dependencies import SessionDep, get_current_active_user
from web.backend.app.auth.models.user import User
from web.backend.app.auth.recent_auth import require_recent_auth
from web.backend.app.auth.schemas.oauth import UserOAuthAccountRead
from web.backend.app.auth.schemas.user import UserRead, UserUpdate
from web.backend.app.auth.services.oauth_account_service import (
    get_for_user,
    normalize_provider,
    unlink_oauth_account,
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
