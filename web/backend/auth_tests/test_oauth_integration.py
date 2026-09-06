from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from web.backend.app.auth import oauth, oauth_api
from web.backend.app.auth.config import get_settings
from web.backend.app.auth.models import User, UserOAuthAccount
from web.backend.app.auth.schemas.oauth import OAuthIdentity
from web.backend.auth_tests.test_local_flows import ACCOUNT, signup


@pytest.fixture
def providers(monkeypatch):
    for name in [
        "GITHUB_CLIENT_ID",
        "GITHUB_CLIENT_SECRET",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
    ]:
        monkeypatch.setenv(name, "NOT_A_SECRET_TEST_SENTINEL")
    get_settings.cache_clear()


def callback(client, provider, *, link=False, state_override=None):
    start = client.get(
        f"/api/v1/auth/oauth/{provider}/{'link' if link else 'login'}", follow_redirects=False
    )
    assert start.status_code == 302, start.text
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    return client.get(
        f"/api/v1/auth/oauth/{provider}/callback",
        params={"state": state_override or state, "code": "test-code"},
        follow_redirects=False,
    )


@pytest.mark.parametrize("provider", ["github", "google"])
def test_oauth_login_collision_explicit_link_and_unlink(
    auth_client, auth_engine, providers, monkeypatch, provider
):
    identity = OAuthIdentity(
        provider=provider, subject="123", email=ACCOUNT["email"], email_verified=True
    )
    exchange = AsyncMock(return_value=identity)
    monkeypatch.setattr(oauth_api, "exchange_oauth_code", exchange)
    headers = signup(auth_client)
    collision = callback(auth_client, provider)
    assert "OAUTH_EMAIL_CONFLICT" in collision.headers["location"]
    linked = callback(auth_client, provider, link=True)
    assert "oauth_link=success" in linked.headers["location"]
    accounts = auth_client.get("/api/v1/users/me/oauth-accounts").json()
    assert [a["provider"] for a in accounts] == [provider]
    with Session(auth_engine) as session:
        assert len(session.scalars(select(User)).all()) == 1
        assert session.scalar(select(UserOAuthAccount.provider_subject)) == "123"
    assert auth_client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    logged = callback(auth_client, provider)
    assert "/auth/callback" in logged.headers["location"]
    assert auth_client.get("/api/v1/auth/me").json()["email"] == ACCOUNT["email"]
    csrf = auth_client.cookies.get("ocp_hub_csrf_token")
    assert auth_client.delete(f"/api/v1/users/me/oauth-accounts/{provider}").status_code == 403
    assert (
        auth_client.delete(
            f"/api/v1/users/me/oauth-accounts/{provider}", headers={"x-csrf-token": csrf}
        ).status_code
        == 204
    )


def test_state_mismatch_does_not_exchange(auth_client, providers, monkeypatch):
    exchange = AsyncMock()
    monkeypatch.setattr(oauth_api, "exchange_oauth_code", exchange)
    result = callback(auth_client, "github", state_override="wrong-state")
    assert "INVALID_OAUTH_STATE" in result.headers["location"]
    exchange.assert_not_called()


def test_new_oauth_account_missing_email_and_last_method(auth_client, providers, monkeypatch):
    monkeypatch.setattr(
        oauth_api,
        "exchange_oauth_code",
        AsyncMock(
            return_value=OAuthIdentity(provider="github", subject="123", username="test-user")
        ),
    )
    result = callback(auth_client, "github")
    assert "oauth_onboarding" in result.headers["location"]
    user = auth_client.get("/api/v1/auth/me").json()
    assert user["email_pending"] and not user["is_verified"]
    csrf = {"x-csrf-token": auth_client.cookies.get("ocp_hub_csrf_token")}
    assert (
        auth_client.delete("/api/v1/users/me/oauth-accounts/github", headers=csrf).status_code
        == 409
    )
    result = auth_client.post(
        "/api/v1/auth/oauth/complete-email", headers=csrf, json={"email": "new@example.org"}
    )
    assert result.status_code == 200


@pytest.mark.parametrize("path", ["https://evil.test", "//evil.test", "/\\evil.test", "/\x00evil"])
def test_safe_redirects(path):
    assert oauth.safe_redirect_path(path) == "/"


def test_signed_state_tampering():
    flow = oauth.OAuthFlowState("state", "link", "/profil", "user-id")
    encoded = oauth.encode_oauth_flow(flow)
    assert oauth.decode_oauth_flow(encoded) == flow
    assert oauth.decode_oauth_flow(encoded + "x") is None


def test_provider_discovery_no_secrets(auth_client):
    assert auth_client.get("/api/v1/auth/providers").json() == {"providers": []}
    assert auth_client.get("/api/v1/auth/oauth/github/login").status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["github", "google"])
@pytest.mark.parametrize("verified", [True, False])
async def test_network_exchange_trusts_only_verified_email(
    monkeypatch, providers, provider, verified
):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_token.return_value = {"access_token": "NOT_A_SECRET_TEST_SENTINEL"}
    monkeypatch.setattr(oauth, "AsyncOAuth2Client", lambda **kwargs: client)

    def respond(request):
        if request.url.path == "/user/emails":
            data = [{"primary": True, "verified": verified, "email": "test@example.org"}]
        else:
            data = {
                "id": 123,
                "sub": "123",
                "email": "test@example.org",
                "email_verified": verified,
            }
        return httpx.Response(200, json=data)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        oauth.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond)),
    )
    identity = await oauth.exchange_oauth_code(provider, "test-code")
    assert identity.email == ("test@example.org" if verified else None)
    assert identity.email_verified is verified


def test_signed_state_expires(monkeypatch):
    monkeypatch.setattr(oauth.time, "time", lambda: 1000)
    value = oauth.encode_oauth_flow(oauth.OAuthFlowState("state", "login", "/"))
    monkeypatch.setattr(oauth.time, "time", lambda: 1601)
    assert oauth.decode_oauth_flow(value) is None
