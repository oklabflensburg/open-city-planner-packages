# Adapted from open-city-planner 2238e18 (AGPL-3.0-only).
import hmac
import logging
import urllib.parse
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from web.backend.app.auth.config import get_settings
from web.backend.app.auth.csrf import validate_csrf
from web.backend.app.auth.dependencies import SessionDep, get_current_active_user, get_optional_user
from web.backend.app.auth.models.user import User
from web.backend.app.auth.oauth import (
    OAuthFlowState,
    authorization_url,
    configured_providers,
    create_oauth_state,
    decode_oauth_flow,
    encode_oauth_flow,
    exchange_oauth_code,
    oauth_cookie_name,
    provider_is_configured,
    safe_redirect_path,
)
from web.backend.app.auth.recent_auth import require_recent_auth
from web.backend.app.auth.schemas.auth import VerificationResponse
from web.backend.app.auth.schemas.oauth import OAuthEmailCompletionRequest, OAuthProviderRead
from web.backend.app.auth.services.auth_service import complete_oauth_email, issue_session
from web.backend.app.auth.services.oauth_account_service import (
    authenticate_oauth_identity,
    get_for_user_provider,
    link_oauth_account,
    normalize_provider,
)
from web.backend.app.auth.services.rate_limit import check_rate_limit, rate_limit_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/providers")
async def get_auth_providers() -> dict[str, list[str]]:
    return {"providers": configured_providers()}


@router.get("/oauth/providers", response_model=list[OAuthProviderRead])
async def get_oauth_providers() -> list[OAuthProviderRead]:
    return [
        OAuthProviderRead(id=provider, label=provider_label(provider))
        for provider in configured_providers()
    ]


@router.post("/oauth/complete-email", response_model=VerificationResponse)
async def post_complete_oauth_email(
    payload: OAuthEmailCompletionRequest,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> VerificationResponse:
    validate_csrf(request)
    await complete_oauth_email(session, user, str(payload.email))
    return VerificationResponse(
        status="verification_sent",
        code="VERIFICATION_EMAIL_SENT",
        message=("Bitte bestätigen Sie Ihre E-Mail-Adresse über den zugesandten Link."),
    )


@router.get("/oauth/{provider}/login")
async def oauth_login(
    provider: str, request: Request, redirect: str | None = None
) -> RedirectResponse:
    provider = normalize_provider(provider)
    if not provider_is_configured(provider):
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "OAUTH_PROVIDER_DISABLED",
                    "message": "Dieser OAuth-Provider ist nicht konfiguriert.",
                }
            },
        )
    await check_rate_limit(rate_limit_key(request, f"oauth-start:{provider}"))
    state = create_oauth_state()
    response = RedirectResponse(authorization_url(provider, state), status_code=302)
    settings = get_settings()
    response.set_cookie(
        oauth_cookie_name(provider),
        encode_oauth_flow(
            OAuthFlowState(state=state, mode="login", redirect_path=safe_redirect_path(redirect))
        ),
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=600,
        path="/api/v1/auth/oauth",
        domain=settings.auth_cookie_domain,
    )
    return response


@router.get("/oauth/{provider}/link")
async def oauth_link(
    provider: str,
    session: SessionDep,
    request: Request,
    user: Annotated[User, Depends(get_current_active_user)],
) -> RedirectResponse:
    require_recent_auth(request)
    provider = normalize_provider(provider)
    if not provider_is_configured(provider):
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "OAUTH_PROVIDER_DISABLED",
                    "message": "Dieser OAuth-Provider ist nicht konfiguriert.",
                }
            },
        )
    settings = get_settings()
    if await get_for_user_provider(session, user.id, provider):
        response = oauth_link_result_redirect(provider, success="already_connected")
        clear_oauth_cookie(response, provider)
        return response
    state = create_oauth_state()
    response = RedirectResponse(authorization_url(provider, state), status_code=302)
    response.set_cookie(
        oauth_cookie_name(provider),
        encode_oauth_flow(
            OAuthFlowState(state=state, mode="link", redirect_path="/profil", user_id=str(user.id))
        ),
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=600,
        path="/api/v1/auth/oauth",
        domain=settings.auth_cookie_domain,
    )
    return response


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    state: str,
    session: SessionDep,
    request: Request,
    response: Response,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    provider = normalize_provider(provider)
    settings = get_settings()
    if not provider_is_configured(provider):
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "OAUTH_PROVIDER_DISABLED",
                    "message": "Dieser OAuth-Provider ist nicht konfiguriert.",
                }
            },
        )
    flow = decode_oauth_flow(request.cookies.get(oauth_cookie_name(provider)))
    if not flow:
        redirect_response = oauth_login_error_redirect("INVALID_OAUTH_STATE")
        clear_oauth_cookie(redirect_response, provider)
        return redirect_response
    if not hmac.compare_digest(flow.state, state):
        return oauth_flow_error_redirect(flow.mode, provider, "INVALID_OAUTH_STATE")
    if error or not code:
        return oauth_flow_error_redirect(flow.mode, provider, "OAUTH_ACCESS_DENIED")
    try:
        identity = await exchange_oauth_code(provider, code)
    except HTTPException:
        return oauth_flow_error_redirect(flow.mode, provider, flow_error_code(flow.mode))
    except Exception:
        logger.warning("OAuth code exchange failed provider=%s", provider)
        return oauth_flow_error_redirect(flow.mode, provider, flow_error_code(flow.mode))
    if flow.mode == "link":
        current_user = await get_optional_user(request, session)
        if not current_user or str(current_user.id) != flow.user_id:
            return oauth_flow_error_redirect("link", provider, "AUTH_REQUIRED")
        try:
            await link_oauth_account(session, current_user, identity)
        except HTTPException as exc:
            code_value = (
                exc.detail.get("error", {}).get("code", "OAUTH_LINK_FAILED")
                if isinstance(exc.detail, dict)
                else "OAUTH_LINK_FAILED"
            )
            redirect_response = oauth_link_result_redirect(provider, error=code_value)
            clear_oauth_cookie(redirect_response, provider)
            return redirect_response
        redirect_response = oauth_link_result_redirect(provider, success="success")
        clear_oauth_cookie(redirect_response, provider)
        return redirect_response
    try:
        user = await authenticate_oauth_identity(session, identity)
    except HTTPException as exc:
        code_value = (
            exc.detail.get("error", {}).get("code", "OAUTH_LOGIN_FAILED")
            if isinstance(exc.detail, dict)
            else "OAUTH_LOGIN_FAILED"
        )
        return oauth_flow_error_redirect("login", provider, code_value)
    callback_url = f"{settings.app_base_url.rstrip('/')}/auth/callback"
    redirect_path = (
        "/profil?oauth_onboarding=email"
        if user.email_pending
        else safe_redirect_path(flow.redirect_path)
    )
    callback_query = urllib.parse.urlencode({"redirect": redirect_path})
    redirect_response = RedirectResponse(f"{callback_url}?{callback_query}", status_code=302)
    await issue_session(session, redirect_response, user, request, amr=["oauth"])
    redirect_response.delete_cookie(
        oauth_cookie_name(provider), path="/api/v1/auth/oauth", domain=settings.auth_cookie_domain
    )
    return redirect_response


def provider_label(provider: str) -> str:
    return {"github": "GitHub", "google": "Google"}.get(provider, provider.capitalize())


def oauth_login_error_redirect(code: str) -> RedirectResponse:
    settings = get_settings()
    return RedirectResponse(
        f"{settings.app_base_url.rstrip('/')}/anmelden?auth_error={code}", status_code=302
    )


def oauth_link_result_redirect(
    provider: str, *, success: str | None = None, error: str | None = None
) -> RedirectResponse:
    settings = get_settings()
    query = {"provider": normalize_provider(provider)}
    if success:
        query["oauth_link"] = success
    if error:
        query["oauth_link_error"] = error
    return RedirectResponse(
        f"{settings.app_base_url.rstrip('/')}/profil?{urllib.parse.urlencode(query)}",
        status_code=302,
    )


def oauth_flow_error_redirect(mode: str, provider: str, code: str) -> RedirectResponse:
    if mode == "link":
        response = oauth_link_result_redirect(provider, error=code)
    else:
        response = oauth_login_error_redirect(code)
    clear_oauth_cookie(response, provider)
    return response


def flow_error_code(mode: str) -> str:
    return "OAUTH_LINK_FAILED" if mode == "link" else "OAUTH_LOGIN_FAILED"


def clear_oauth_cookie(response: RedirectResponse, provider: str) -> None:
    settings = get_settings()
    response.delete_cookie(
        oauth_cookie_name(provider), path="/api/v1/auth/oauth", domain=settings.auth_cookie_domain
    )
