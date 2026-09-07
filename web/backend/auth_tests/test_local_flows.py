from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from web.backend.app.auth.models import (
    EmailVerificationToken,
    PasswordResetToken,
    User,
    UserSession,
)
from web.backend.app.auth.tokens import hash_token

ACCOUNT = {"email": "account@example.org", "password": "NOT_A_SECRET_TEST_PASSPHRASE"}


def signup(client):
    response = client.post("/api/v1/auth/signup", json=ACCOUNT)
    assert response.status_code == 201, response.text
    return {"x-csrf-token": response.json()["csrf_token"]}


def test_signup_me_logout_login_and_csrf(auth_client, auth_engine):
    headers = signup(auth_client)
    assert auth_client.get("/api/v1/auth/me").json()["email"] == ACCOUNT["email"]
    assert auth_client.get("/api/v1/auth/me").headers["cache-control"] == "no-store"
    assert auth_client.post("/api/v1/auth/logout").status_code == 403
    assert auth_client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert auth_client.get("/api/v1/auth/me").status_code == 401
    assert auth_client.post("/api/v1/auth/login", json=ACCOUNT).status_code == 200
    wrong = {**ACCOUNT, "password": "NOT_A_SECRET_WRONG_SENTINEL"}
    assert auth_client.post("/api/v1/auth/login", json=wrong).status_code == 401
    assert auth_client.post("/api/v1/auth/signup", json=ACCOUNT).status_code == 409
    with Session(auth_engine) as session:
        assert session.scalar(select(User.password_hash)).startswith("$argon2")
        assert session.scalar(select(User.roles)) == []


def test_rotation_reuse_and_origin(auth_client, auth_engine):
    signup(auth_client)
    old = auth_client.cookies.get("ocp_hub_refresh_token")
    assert (
        auth_client.post(
            "/api/v1/auth/refresh", headers={"origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert auth_client.post("/api/v1/auth/refresh").status_code == 200
    current = auth_client.cookies.get("ocp_hub_refresh_token")
    assert current != old
    cookie = {"cookie": f"ocp_hub_refresh_token={old}"}
    assert auth_client.post("/api/v1/auth/refresh", headers=cookie).status_code == 409
    with Session(auth_engine) as session:
        session.execute(
            update(UserSession)
            .where(UserSession.token_hash == hash_token(old))
            .values(rotated_at=datetime.now(UTC) - timedelta(seconds=30))
        )
        session.commit()
    assert auth_client.post("/api/v1/auth/refresh", headers=cookie).status_code == 401
    assert (
        auth_client.post(
            "/api/v1/auth/refresh", headers={"cookie": f"ocp_hub_refresh_token={current}"}
        ).status_code
        == 401
    )


def test_email_verification_and_reset(auth_client, auth_engine, sent_mail):
    signup(auth_client)
    verification, reset = sent_mail
    token = verification.call_args.args[2]
    with Session(auth_engine) as session:
        assert session.scalar(select(EmailVerificationToken.token_hash)) == hash_token(token)
    assert (
        auth_client.post("/api/v1/auth/verify-email", json={"token": token}).json()["status"]
        == "verified"
    )
    assert (
        auth_client.post("/api/v1/auth/verify-email", json={"token": token}).json()["status"]
        == "already_verified"
    )
    forgot = auth_client.post("/api/v1/auth/forgot-password", json={"email": ACCOUNT["email"]})
    unknown = auth_client.post(
        "/api/v1/auth/forgot-password", json={"email": "missing@example.org"}
    )
    assert forgot.json() == unknown.json()
    reset_token = reset.call_args.args[2]
    with Session(auth_engine) as session:
        assert session.scalar(select(PasswordResetToken.token_hash)) == hash_token(reset_token)
    payload = {"token": reset_token, "password": "NOT_A_SECRET_REPLACEMENT_SENTINEL"}
    payload["password_confirm"] = payload["password"]
    assert auth_client.post("/api/v1/auth/reset-password", json=payload).status_code == 200
    assert auth_client.post("/api/v1/auth/reset-password", json=payload).status_code == 400
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401
    assert auth_client.post("/api/v1/auth/login", json=ACCOUNT).status_code == 401
    assert (
        auth_client.post(
            "/api/v1/auth/login", json={**ACCOUNT, "password": payload["password"]}
        ).status_code
        == 200
    )


def test_disabled_user_and_limits(auth_client, auth_engine):
    signup(auth_client)
    with Session(auth_engine) as session:
        session.execute(update(User).values(is_active=False))
        session.commit()
    assert auth_client.get("/api/v1/auth/me").status_code == 403
    assert auth_client.post("/api/v1/auth/login", json=ACCOUNT).status_code == 403
    for _ in range(7):
        auth_client.post("/api/v1/auth/login", json=ACCOUNT)
    limited = auth_client.post("/api/v1/auth/login", json=ACCOUNT)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0


def test_invalid_refresh_clears_browser_cookies(auth_client):
    signup(auth_client)
    auth_client.cookies.set(
        "ocp_hub_refresh_token", "NOT_A_SECRET_INVALID_TOKEN", domain="testserver.local", path="/"
    )
    response = auth_client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert len(response.headers.get_list("set-cookie")) == 3
    assert not any(cookie.name.startswith("ocp_hub_") for cookie in auth_client.cookies.jar)


def test_profile_cannot_grant_registry_roles(auth_client, auth_engine):
    headers = signup(auth_client)
    response = auth_client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"display_name": "Test", "roles": ["admin"], "is_superuser": True},
    )
    assert response.status_code == 200
    with Session(auth_engine) as session:
        user = session.scalar(select(User))
        assert user.roles == [] and not user.is_superuser


def test_credentialed_auth_cors_does_not_change_registry_policy(auth_client):
    headers = {
        "origin": "http://localhost:3000",
        "access-control-request-method": "POST",
        "access-control-request-headers": "content-type,x-csrf-token",
    }
    assert auth_client.options("/api/v1/packages", headers=headers).status_code == 400
    response = auth_client.options("/api/v1/auth/login", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-credentials"] == "true"
    headers["origin"] = "https://evil.test"
    assert auth_client.options("/api/v1/auth/login", headers=headers).status_code == 400


def test_profile_metadata_exposes_password_status_without_hash(auth_client, auth_engine):
    signup(auth_client)
    response = auth_client.get("/api/v1/users/me")
    assert response.json()["has_local_password"] is True
    assert "password_hash" not in response.json()
    assert "created_at" in response.json()
    with Session(auth_engine) as session:
        session.execute(update(User).values(password_hash=None))
        session.commit()
    response = auth_client.get("/api/v1/users/me")
    assert response.json()["has_local_password"] is False
    assert "password_hash" not in response.json()


def test_linked_account_metadata_contains_avatar_but_no_provider_credentials(
    auth_client, auth_engine
):
    from web.backend.app.auth.models import UserOAuthAccount

    signup(auth_client)
    with Session(auth_engine) as session:
        user = session.scalar(select(User))
        session.add(
            UserOAuthAccount(
                user_id=user.id,
                provider="github",
                provider_subject="PRIVATE_PROVIDER_SUBJECT",
                provider_username="mara.codes",
                provider_email="mara@example.org",
                provider_avatar_url="https://avatars.example.org/mara.png",
                provider_profile_url="https://github.com/example",
            )
        )
        session.commit()
    response = auth_client.get("/api/v1/users/me/oauth-accounts")
    assert response.status_code == 200
    assert response.json()[0]["provider_avatar_url"] == "https://avatars.example.org/mara.png"
    assert "PRIVATE_PROVIDER_SUBJECT" not in response.text
    assert "password_hash" not in response.text
