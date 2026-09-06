# Adapted from open-city-planner 2238e18 (AGPL-3.0-only).
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from web.backend.app.auth.config import get_settings
from web.backend.app.auth.csrf import create_csrf_token, validate_csrf, validate_refresh_origin
from web.backend.app.auth.dependencies import SessionDep, get_current_active_user
from web.backend.app.auth.models.user import User
from web.backend.app.auth.recent_auth import require_recent_auth
from web.backend.app.auth.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    MfaChallengeDetailsResponse,
    MfaChallengeResponse,
    MfaDisableRequest,
    MfaRegenerateRequest,
    MfaSecurityStatus,
    MfaVerifyRequest,
    PasskeyAuthenticationVerifyRequest,
    PasskeyMfaOptionsRequest,
    PasskeyMfaVerifyRequest,
    PasskeyRead,
    PasskeyRegistrationVerifyRequest,
    RecoveryCodesResponse,
    ResetPasswordRequest,
    SignupRequest,
    TokenRequest,
    TotpConfirmRequest,
    TotpSetupResponse,
    VerificationResponse,
    WebAuthnOptionsResponse,
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
from web.backend.app.auth.services.email_service import send_mfa_security_email
from web.backend.app.auth.services.mfa_service import (
    available_mfa_methods,
    confirm_totp_setup,
    create_login_challenge,
    disable_mfa,
    login_challenge_details,
    preferred_mfa_method,
    regenerate_recovery_codes,
    revoke_other_sessions,
    security_status,
    start_totp_setup,
    verify_login_challenge,
)
from web.backend.app.auth.services.passkey_service import (
    authentication_options,
    mfa_options,
    registration_options,
    verify_passwordless_login,
    verify_reauthentication,
    verify_registration,
)
from web.backend.app.auth.services.passkey_service import verify_mfa as verify_passkey_mfa
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


@router.post("/refresh", response_model=AuthResponse)
async def post_refresh(session: SessionDep, response: Response, request: Request) -> AuthResponse:
    settings = get_settings()
    validate_refresh_origin(request)
    refresh_token = request.cookies.get(settings.auth_refresh_cookie_name)
    if not refresh_token:
        return refresh_failure(
            response,
            HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": {
                        "code": "REFRESH_TOKEN_MISSING",
                        "message": "Bitte melden Sie sich erneut an.",
                    }
                },
            ),
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
            return refresh_failure(response, exc)
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


def mfa_challenge_token(request: Request, supplied: str | None) -> str:
    token = supplied or request.cookies.get(get_settings().auth_mfa_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "MFA_CHALLENGE_MISSING",
                    "message": ("Die Anmeldung ist abgelaufen. Bitte melden Sie sich erneut an."),
                }
            },
        )
    return token


def clear_mfa_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.auth_mfa_cookie_name, path="/api/v1/auth/mfa", domain=settings.auth_cookie_domain
    )


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
    methods = await available_mfa_methods(session, user.id)
    if methods:
        challenge = await create_login_challenge(session, user, request, primary_method="password")
        return MfaChallengeResponse(
            challenge_token=challenge.token,
            method="passkey" if "passkey" in methods else "totp",
            preferred_method=preferred_mfa_method(methods),
            methods=methods,
            expires_in=challenge.expires_in,
        )
    csrf_token = await issue_session(session, response, user, request, amr=["pwd"])
    return AuthResponse(user=UserRead.model_validate(user), csrf_token=csrf_token)


@router.post("/passkeys/register/options", response_model=WebAuthnOptionsResponse)
async def post_passkey_registration_options(
    session: SessionDep, request: Request, user: Annotated[User, Depends(get_current_active_user)]
) -> WebAuthnOptionsResponse:
    validate_csrf(request)
    require_recent_auth(request)
    await check_rate_limit(f"passkey-register-options:{user.id}", attempts=5, window_seconds=600)
    result = await registration_options(session, user, request)
    return WebAuthnOptionsResponse(ceremony_token=result.token, options=result.options)


@router.post("/passkeys/register/verify", response_model=PasskeyRead)
async def post_passkey_registration_verify(
    payload: PasskeyRegistrationVerifyRequest,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> PasskeyRead:
    validate_csrf(request)
    require_recent_auth(request)
    await check_rate_limit(f"passkey-register-verify:{user.id}", attempts=5, window_seconds=600)
    record = await verify_registration(
        session, user, payload.ceremony_token, payload.credential, payload.name
    )
    await send_mfa_security_email(session, user, "passkey_added")
    return PasskeyRead.model_validate(record)


@router.post("/passkeys/login/options", response_model=WebAuthnOptionsResponse)
async def post_passkey_login_options(
    session: SessionDep, request: Request
) -> WebAuthnOptionsResponse:
    await check_rate_limit(
        rate_limit_key(request, "passkey-login-options"), attempts=10, window_seconds=300
    )
    result = await authentication_options(session, request)
    return WebAuthnOptionsResponse(ceremony_token=result.token, options=result.options)


@router.post("/passkeys/login/verify", response_model=AuthResponse)
async def post_passkey_login_verify(
    payload: PasskeyAuthenticationVerifyRequest,
    session: SessionDep,
    response: Response,
    request: Request,
) -> AuthResponse:
    await check_rate_limit(
        rate_limit_key(request, "passkey-login-verify"), attempts=8, window_seconds=300
    )
    user = await verify_passwordless_login(session, payload.ceremony_token, payload.credential)
    csrf_token = await issue_session(session, response, user, request, amr=["webauthn"])
    return AuthResponse(user=UserRead.model_validate(user), csrf_token=csrf_token)


@router.post("/mfa/passkey/options", response_model=WebAuthnOptionsResponse)
async def post_mfa_passkey_options(
    payload: PasskeyMfaOptionsRequest, session: SessionDep, request: Request
) -> WebAuthnOptionsResponse:
    challenge_token = mfa_challenge_token(request, payload.challenge_token)
    fingerprint = hash_token(challenge_token)[:24]
    await check_rate_limit(
        rate_limit_key(request, "passkey-mfa-options", fingerprint), attempts=5, window_seconds=300
    )
    result = await mfa_options(session, request, challenge_token)
    return WebAuthnOptionsResponse(ceremony_token=result.token, options=result.options)


@router.get("/mfa/challenge", response_model=MfaChallengeDetailsResponse)
async def get_mfa_challenge(session: SessionDep, request: Request) -> MfaChallengeDetailsResponse:
    challenge_token = mfa_challenge_token(request, None)
    fingerprint = hash_token(challenge_token)[:24]
    await check_rate_limit(
        rate_limit_key(request, "mfa-challenge", fingerprint), attempts=10, window_seconds=300
    )
    details = await login_challenge_details(session, challenge_token)
    return MfaChallengeDetailsResponse(
        preferred_method=details.preferred_method,
        methods=details.methods,
        expires_in=details.expires_in,
    )


@router.post("/mfa/passkey/verify", response_model=AuthResponse)
async def post_mfa_passkey_verify(
    payload: PasskeyMfaVerifyRequest, session: SessionDep, response: Response, request: Request
) -> AuthResponse:
    challenge_token = mfa_challenge_token(request, payload.challenge_token)
    fingerprint = hash_token(challenge_token)[:24]
    await check_rate_limit(
        rate_limit_key(request, "passkey-mfa-verify", fingerprint), attempts=5, window_seconds=300
    )
    user, primary_method = await verify_passkey_mfa(
        session, challenge_token, payload.ceremony_token, payload.credential
    )
    primary = "oauth" if primary_method.startswith("oauth") else "pwd"
    csrf_token = await issue_session(session, response, user, request, amr=[primary, "webauthn"])
    clear_mfa_cookie(response)
    return AuthResponse(user=UserRead.model_validate(user), csrf_token=csrf_token)


@router.post("/passkeys/reauth/options", response_model=WebAuthnOptionsResponse)
async def post_passkey_reauth_options(
    session: SessionDep, request: Request, user: Annotated[User, Depends(get_current_active_user)]
) -> WebAuthnOptionsResponse:
    validate_csrf(request)
    await check_rate_limit(f"passkey-reauth-options:{user.id}", attempts=5, window_seconds=300)
    result = await authentication_options(
        session, request, user_id=user.id, purpose="passkey_step_up"
    )
    return WebAuthnOptionsResponse(ceremony_token=result.token, options=result.options)


@router.post("/passkeys/reauth/verify", response_model=AuthResponse)
async def post_passkey_reauth_verify(
    payload: PasskeyAuthenticationVerifyRequest,
    session: SessionDep,
    response: Response,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> AuthResponse:
    validate_csrf(request)
    await check_rate_limit(f"passkey-reauth-verify:{user.id}", attempts=5, window_seconds=300)
    verified_user = await verify_reauthentication(
        session, user.id, payload.ceremony_token, payload.credential
    )
    await revoke_current_session(
        session, request.cookies.get(get_settings().auth_refresh_cookie_name)
    )
    csrf_token = await issue_session(session, response, verified_user, request, amr=["webauthn"])
    return AuthResponse(user=UserRead.model_validate(verified_user), csrf_token=csrf_token)


@router.post("/mfa/verify", response_model=AuthResponse)
async def post_mfa_verify(
    payload: MfaVerifyRequest, session: SessionDep, response: Response, request: Request
) -> AuthResponse:
    settings = get_settings()
    challenge_token = mfa_challenge_token(request, payload.challenge_token)
    fingerprint = hash_token(challenge_token)[:24]
    await check_rate_limit(
        rate_limit_key(request, "mfa-verify", fingerprint),
        attempts=settings.mfa_max_attempts,
        window_seconds=settings.mfa_challenge_expire_seconds,
        code="MFA_TOO_MANY_ATTEMPTS",
        message=("Zu viele Fehlversuche. Bitte melden Sie sich erneut an."),
    )
    user, factor, primary_method = await verify_login_challenge(
        session, challenge_token, code=payload.code, recovery_code=payload.recovery_code
    )
    primary = "oauth" if primary_method.startswith("oauth") else "pwd"
    csrf_token = await issue_session(
        session, response, user, request, amr=[primary, "otp" if factor == "totp" else "recovery"]
    )
    if factor == "recovery":
        await send_mfa_security_email(session, user, "recovery_used")
    clear_mfa_cookie(response)
    return AuthResponse(user=UserRead.model_validate(user), csrf_token=csrf_token)


@router.get("/mfa/security", response_model=MfaSecurityStatus)
async def get_mfa_security(
    session: SessionDep, user: Annotated[User, Depends(get_current_active_user)]
) -> MfaSecurityStatus:
    return MfaSecurityStatus(**await security_status(session, user.id))


@router.post("/mfa/totp/setup", response_model=TotpSetupResponse)
async def post_totp_setup(
    session: SessionDep, request: Request, user: Annotated[User, Depends(get_current_active_user)]
) -> TotpSetupResponse:
    validate_csrf(request)
    require_recent_auth(request)
    settings = get_settings()
    await check_rate_limit(f"mfa-setup:{user.id}", attempts=3, window_seconds=600)
    secret, uri = await start_totp_setup(session, user)
    return TotpSetupResponse(
        secret=secret,
        otpauth_uri=uri,
        issuer=settings.mfa_totp_issuer,
        account_name=user.email,
        expires_in=settings.mfa_setup_expire_seconds,
    )


@router.post("/mfa/totp/confirm", response_model=RecoveryCodesResponse)
async def post_totp_confirm(
    payload: TotpConfirmRequest,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> RecoveryCodesResponse:
    validate_csrf(request)
    await check_rate_limit(f"mfa-confirm:{user.id}", attempts=5, window_seconds=600)
    codes = await confirm_totp_setup(session, user, payload.code)
    await revoke_other_sessions(session, user.id, request, "mfa_enabled")
    await send_mfa_security_email(session, user, "enabled")
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/mfa/recovery-codes", response_model=RecoveryCodesResponse)
async def post_recovery_codes(
    payload: MfaRegenerateRequest,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> RecoveryCodesResponse:
    validate_csrf(request)
    await check_rate_limit(f"mfa-recovery-regenerate:{user.id}", attempts=3, window_seconds=600)
    codes = await regenerate_recovery_codes(
        session,
        user,
        current_password=payload.current_password,
        code=payload.code,
        recovery_code=payload.recovery_code,
    )
    await revoke_other_sessions(session, user.id, request, "mfa_recovery_regenerated")
    await send_mfa_security_email(session, user, "recovery_regenerated")
    return RecoveryCodesResponse(recovery_codes=codes)


@router.delete("/mfa/totp", response_model=MessageResponse)
async def delete_totp(
    payload: MfaDisableRequest,
    session: SessionDep,
    response: Response,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> MessageResponse:
    validate_csrf(request)
    await check_rate_limit(f"mfa-disable:{user.id}", attempts=3, window_seconds=600)
    await disable_mfa(
        session,
        user,
        current_password=payload.current_password,
        code=payload.code,
        recovery_code=payload.recovery_code,
    )
    clear_auth_cookies(response)
    await send_mfa_security_email(session, user, "disabled")
    return MessageResponse(
        message=(
            "Zwei-Faktor-Authentifizierung wurde deaktiviert. Bitte melden Sie sich erneut an."
        )
    )


def refresh_failure(response: Response, error: HTTPException) -> JSONResponse:
    # Raising HTTPException discards cookies set on FastAPI's injected Response.
    # Return the actual failure response so the browser also clears invalid sessions.
    clear_auth_cookies(response)
    failure = JSONResponse(
        {"detail": error.detail}, status_code=error.status_code, headers=error.headers
    )
    failure.raw_headers.extend(
        (name, value) for name, value in response.raw_headers if name == b"set-cookie"
    )
    return failure
