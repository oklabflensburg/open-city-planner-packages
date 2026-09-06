from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from web.backend.app.auth.config import get_settings
from web.backend.app.auth.models import (
    AuthMfaChallenge,
    UserMfaMethod,
    UserMfaRecoveryCode,
    WebAuthnChallenge,
)
from web.backend.auth_tests.test_local_flows import ACCOUNT, signup


@pytest.fixture
def encryption(monkeypatch):
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()


def enable_totp(client):
    csrf = signup(client)
    setup = client.post("/api/v1/auth/mfa/totp/setup", headers=csrf)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    confirmed = client.post(
        "/api/v1/auth/mfa/totp/confirm", headers=csrf, json={"code": pyotp.TOTP(secret).now()}
    )
    assert confirmed.status_code == 200, confirmed.text
    return secret, confirmed.json()["recovery_codes"], csrf


def test_totp_recovery_login_reuse_and_disable(auth_client, auth_engine, encryption):
    secret, codes, csrf = enable_totp(auth_client)
    assert len(codes) == 10 and len(set(codes)) == 10
    with Session(auth_engine) as session:
        method = session.scalar(select(UserMfaMethod))
        assert method.is_enabled and secret not in method.secret_encrypted
        assert codes[0] not in session.scalars(select(UserMfaRecoveryCode.code_hash)).all()
    assert auth_client.post("/api/v1/auth/logout", headers=csrf).status_code == 200
    login = auth_client.post("/api/v1/auth/login", json=ACCOUNT).json()
    assert login["status"] == "mfa_required"
    assert auth_client.get("/api/v1/auth/me").status_code == 401
    token = login["challenge_token"]
    verified = auth_client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_token": token, "recovery_code": codes[0]}
    )
    assert verified.status_code == 200, verified.text
    assert (
        auth_client.post(
            "/api/v1/auth/mfa/verify", json={"challenge_token": token, "recovery_code": codes[1]}
        ).status_code
        == 409
    )
    csrf = {"x-csrf-token": verified.json()["csrf_token"]}
    status = auth_client.get("/api/v1/auth/mfa/security").json()
    assert status["enabled"] and status["recovery_codes_remaining"] == 9
    disabled = auth_client.request(
        "DELETE",
        "/api/v1/auth/mfa/totp",
        headers=csrf,
        json={"current_password": ACCOUNT["password"], "recovery_code": codes[1]},
    )
    assert disabled.status_code == 200, disabled.text
    assert auth_client.get("/api/v1/auth/me").status_code == 401
    assert auth_client.post("/api/v1/auth/login", json=ACCOUNT).json()["status"] == "authenticated"


def test_mfa_challenge_expires_in_database(auth_client, auth_engine, encryption):
    _, _, csrf = enable_totp(auth_client)
    auth_client.post("/api/v1/auth/logout", headers=csrf)
    login = auth_client.post("/api/v1/auth/login", json=ACCOUNT).json()
    with Session(auth_engine) as session:
        session.execute(
            update(AuthMfaChallenge).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        session.commit()
    assert (
        auth_client.post(
            "/api/v1/auth/mfa/verify",
            json={"challenge_token": login["challenge_token"], "code": "123456"},
        ).status_code
        == 400
    )


def test_webauthn_challenge_bound_to_purpose_user_and_expiry(auth_client, auth_engine):
    csrf = signup(auth_client)
    assert auth_client.post("/api/v1/auth/passkeys/register/options").status_code == 403
    options = auth_client.post("/api/v1/auth/passkeys/register/options", headers=csrf)
    assert options.status_code == 200, options.text
    data = options.json()
    assert data["options"]["rp"]["id"] == "localhost"
    assert data["options"]["authenticatorSelection"]["userVerification"] == "required"
    assert data["options"]["challenge"]
    with Session(auth_engine) as session:
        ceremony = session.scalar(select(WebAuthnChallenge))
        assert ceremony.token_hash != data["ceremony_token"]
        assert ceremony.user_id and ceremony.purpose == "passkey_register"
        session.execute(
            update(WebAuthnChallenge).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        session.commit()
    response = auth_client.post(
        "/api/v1/auth/passkeys/register/verify",
        headers=csrf,
        json={"ceremony_token": data["ceremony_token"], "credential": {}},
    )
    assert response.status_code == 400, response.text
    assert "EXPIRED" in response.json()["detail"]["error"]["code"]


def test_self_delete_requires_confirmation_and_credentials(auth_client, auth_engine):
    csrf = signup(auth_client)
    payload = {"confirmation_text": "LÖSCHEN", "current_password": "NOT_A_SECRET_WRONG_SENTINEL"}
    assert (
        auth_client.request("DELETE", "/api/v1/users/me", headers=csrf, json=payload).status_code
        == 403
    )
    payload["current_password"] = ACCOUNT["password"]
    response = auth_client.request("DELETE", "/api/v1/users/me", headers=csrf, json=payload)
    assert response.status_code == 200, response.text
    assert auth_client.get("/api/v1/auth/me").status_code == 401
