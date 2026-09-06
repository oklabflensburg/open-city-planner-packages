# Adapted from open-city-planner 2238e18 (AGPL-3.0-only).
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from web.backend.app.auth.config import get_settings
from web.backend.app.auth.csrf import create_csrf_token, validate_csrf, validate_refresh_origin
from web.backend.app.auth.dependencies import SessionDep, get_current_active_user
from web.backend.app.auth.models.user import User
from web.backend.app.auth.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    ResetPasswordRequest,
    SignupRequest,
    TokenRequest,
    VerificationResponse,
)
from web.backend.app.auth.schemas.user import UserRead
from web.backend.app.auth.services.auth_service import (
    authenticate,
    change_password,
    clear_auth_cookies,
    forgot_password,
    issue_session,
    refresh_session,
    resend_verification,
    reset_password,
    revoke_all_sessions,
    revoke_current_session,
    signup,
    verify_email,
)
from web.backend.app.auth.services.rate_limit import check_rate_limit, rate_limit_key
from web.backend.app.auth.tokens import hash_token

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def post_signup(
    payload: SignupRequest, session: SessionDep, response: Response, request: Request
) -> AuthResponse:
    await check_rate_limit(rate_limit_key(request, "signup"), attempts=10, window_seconds=3600)
    await check_rate_limit(
        rate_limit_key(request, "signup-account", str(payload.email)),
        attempts=3,
        window_seconds=3600,
    )
    user = await signup(session, payload)
    csrf_token = await issue_session(session, response, user, request)
    return AuthResponse(user=UserRead.model_validate(user), csrf_token=csrf_token)


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        401: {"description": "Ungültige E-Mail-Adresse oder ungültiges Passwort"},
        403: {
            "description": (
                "Das Konto kann nicht angemeldet werden. Mögliche Fehlercodes"
                " sind ACCOUNT_SELF_DEACTIVATED und ACCOUNT_DISABLED."
            )
        },
    },
)
async def post_login(
    payload: LoginRequest, session: SessionDep, response: Response, request: Request
) -> LoginResponse:
    await check_rate_limit(rate_limit_key(request, "login", str(payload.email)))
    user = await authenticate(session, payload)
    csrf_token = await issue_session(session, response, user, request, amr=["pwd"])
    return AuthResponse(user=UserRead.model_validate(user), csrf_token=csrf_token)


@router.post("/refresh", response_model=AuthResponse)
async def post_refresh(session: SessionDep, response: Response, request: Request) -> AuthResponse:
    settings = get_settings()
    validate_refresh_origin(request)
    refresh_token = request.cookies.get(settings.auth_refresh_cookie_name)
    if not refresh_token:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "REFRESH_TOKEN_MISSING",
                    "message": "Bitte melden Sie sich erneut an.",
                }
            },
        )
    await check_rate_limit(
        rate_limit_key(request, "refresh", hash_token(refresh_token)[:24]),
        attempts=settings.refresh_rate_limit_attempts,
        window_seconds=settings.refresh_rate_limit_window_seconds,
        code="REFRESH_RATE_LIMITED",
        message="Zu viele Sitzungsaktualisierungen. Bitte kurz warten.",
    )
    try:
        user, csrf_token = await refresh_session(session, response, refresh_token, request)
    except HTTPException as exc:
        error_code = (
            exc.detail.get("error", {}).get("code") if isinstance(exc.detail, dict) else None
        )
        if exc.status_code == status.HTTP_401_UNAUTHORIZED or error_code in {
            "ACCOUNT_SELF_DEACTIVATED",
            "ACCOUNT_DISABLED",
        }:
            clear_auth_cookies(response)
        raise
    return AuthResponse(user=UserRead.model_validate(user), csrf_token=csrf_token)


@router.post("/logout", response_model=MessageResponse)
async def post_logout(session: SessionDep, response: Response, request: Request) -> MessageResponse:
    validate_csrf(request)
    settings = get_settings()
    await revoke_current_session(session, request.cookies.get(settings.auth_refresh_cookie_name))
    clear_auth_cookies(response)
    return MessageResponse(message="Abgemeldet.")


@router.post("/logout-all", response_model=MessageResponse)
async def post_logout_all(
    session: SessionDep,
    response: Response,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> MessageResponse:
    validate_csrf(request)
    await revoke_all_sessions(session, user.id)
    clear_auth_cookies(response)
    return MessageResponse(message="Alle Sitzungen wurden beendet.")


@router.get("/me", response_model=UserRead)
async def get_me(user: Annotated[User, Depends(get_current_active_user)]) -> UserRead:
    return UserRead.model_validate(user)


@router.get("/session", response_model=AuthResponse)
async def get_auth_session(
    request: Request, response: Response, user: Annotated[User, Depends(get_current_active_user)]
) -> AuthResponse:
    settings = get_settings()
    csrf_token = request.cookies.get(settings.auth_csrf_cookie_name) or create_csrf_token()
    if not request.cookies.get(settings.auth_csrf_cookie_name):
        response.set_cookie(
            settings.auth_csrf_cookie_name,
            csrf_token,
            httponly=False,
            secure=settings.auth_cookie_secure,
            samesite=settings.auth_cookie_samesite,
            domain=settings.auth_cookie_domain,
            path=settings.auth_cookie_path,
            max_age=settings.refresh_token_expire_days * 86400,
        )
    return AuthResponse(user=UserRead.model_validate(user), csrf_token=csrf_token)


@router.post("/verify-email", response_model=VerificationResponse)
async def post_verify_email(payload: TokenRequest, session: SessionDep) -> VerificationResponse:
    result = await verify_email(session, payload.token)
    if result.status == "already_verified":
        return VerificationResponse(
            status="already_verified",
            code="EMAIL_ALREADY_VERIFIED",
            message="Die E-Mail-Adresse wurde bereits bestätigt.",
        )
    return VerificationResponse(
        status="verified", code="EMAIL_VERIFIED", message="E-Mail-Adresse bestätigt."
    )


@router.post("/resend-verification", response_model=VerificationResponse)
async def post_resend_verification(
    session: SessionDep, request: Request, user: Annotated[User, Depends(get_current_active_user)]
) -> VerificationResponse:
    validate_csrf(request)
    await check_rate_limit(f"resend-verification:{user.id}")
    sent = await resend_verification(session, user)
    if not sent:
        return VerificationResponse(
            status="already_verified",
            code="EMAIL_ALREADY_VERIFIED",
            message="Die E-Mail-Adresse wurde bereits bestätigt.",
        )
    return VerificationResponse(
        status="verification_sent",
        code="VERIFICATION_EMAIL_SENT",
        message="Bestätigungs-E-Mail wurde gesendet.",
    )


@router.post("/forgot-password", response_model=MessageResponse)
async def post_forgot_password(
    payload: ForgotPasswordRequest, session: SessionDep, request: Request
) -> MessageResponse:
    await check_rate_limit(rate_limit_key(request, "forgot-password", str(payload.email)))
    await forgot_password(session, str(payload.email), request)
    return MessageResponse(
        message=(
            "Wenn ein Konto mit dieser E-Mail-Adresse existiert, wurde ei"
            "ne E-Mail zum Zurücksetzen des Passworts versendet."
        )
    )


@router.post("/reset-password", response_model=MessageResponse)
async def post_reset_password(
    payload: ResetPasswordRequest, session: SessionDep, request: Request
) -> MessageResponse:
    await check_rate_limit(
        rate_limit_key(request, "reset-password", hash_token(payload.token)[:24])
    )
    await reset_password(session, payload.token, payload.password)
    return MessageResponse(message="Passwort wurde zurückgesetzt.")


@router.post("/change-password", response_model=MessageResponse)
async def post_change_password(
    payload: ChangePasswordRequest,
    session: SessionDep,
    response: Response,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> MessageResponse:
    validate_csrf(request)
    await change_password(session, user, payload.current_password, payload.new_password)
    clear_auth_cookies(response)
    return MessageResponse(message="Passwort wurde geändert. Bitte melden Sie sich erneut an.")
