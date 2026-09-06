"""Auth migrations and constraints against disposable PostgreSQL schemas."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from web.backend.app.auth.models import (
    AuthAuditLog,
    AuthMfaChallenge,
    EmailVerificationToken,
    PasswordResetToken,
    User,
    UserMfaMethod,
    UserMfaRecoveryCode,
    UserOAuthAccount,
    UserSession,
    UserWebAuthnCredential,
    WebAuthnChallenge,
)
from web.backend.app.auth.models.base import Base
from web.backend.app.auth.tokens import generate_token, hash_token
from web.backend.app.registry_import_v1 import import_registry
from web.backend.db_tests.conftest import ROOT, migration_config
from web.backend.db_tests.test_registry_database import snapshot


def auth_config(connection):
    config = Config(str(ROOT / "web/backend/auth_alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def auth_engine(pg_engine):
    with pg_engine.begin() as connection:
        command.upgrade(auth_config(connection), "head")
    return pg_engine


def test_empty_database_roundtrip(pg_engine):
    with pg_engine.begin() as connection:
        command.downgrade(migration_config(connection), "base")
        command.upgrade(auth_config(connection), "head")
        assert set(Base.metadata.tables) <= set(inspect(connection).get_table_names())
        command.downgrade(auth_config(connection), "base")
        assert set(inspect(connection).get_table_names()) == {
            "alembic_version",
            "auth_alembic_version",
        }
        assert "account_deactivation_reason" not in {
            enum["name"] for enum in inspect(connection).get_enums()
        }
        command.upgrade(auth_config(connection), "head")
        context = MigrationContext.configure(
            connection,
            opts={
                "version_table": "auth_alembic_version",
                "include_object": lambda obj, name, kind, reflected, other: (
                    kind != "table" or name in Base.metadata.tables
                ),
            },
        )
        assert compare_metadata(context, Base.metadata) == []


def test_existing_registry_unchanged(pg_engine):
    import_registry(pg_engine, ROOT / "registry")
    before = snapshot(pg_engine)
    with pg_engine.begin() as connection:
        command.upgrade(auth_config(connection), "head")
        command.upgrade(auth_config(connection), "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0049_promotions"
        )
        assert connection.scalar(text("SELECT version_num FROM auth_alembic_version")) == (
            "0063_auth_persistence"
        )
    assert snapshot(pg_engine) == before
    with pg_engine.begin() as connection:
        command.downgrade(auth_config(connection), "base")
    assert snapshot(pg_engine) == before


def test_email_case_insensitive_unique(auth_engine):
    with Session(auth_engine) as session:
        session.add(User(email="Account@example.test"))
        session.commit()
        session.add(User(email="account@example.test"))
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize("collision", ["identity", "provider", "unsupported"])
def test_oauth_identity_constraints(auth_engine, collision):
    with Session(auth_engine) as session:
        owner, other = User(email="owner@example.test"), User(email="other@example.test")
        session.add_all([owner, other])
        session.flush()
        session.add(UserOAuthAccount(user_id=owner.id, provider="github", provider_subject="123"))
        session.commit()
        session.add(
            UserOAuthAccount(
                user_id=other.id if collision == "identity" else owner.id,
                provider="unsupported" if collision == "unsupported" else "github",
                provider_subject="123" if collision == "identity" else "456",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_security_records_persist_and_cascade_without_plain_tokens(auth_engine):
    token = generate_token()
    expires = datetime.now(UTC) + timedelta(hours=1)
    with Session(auth_engine) as session:
        user = User(email="owner@example.test")
        session.add(user)
        session.flush()
        user_id = user.id
        challenge = AuthMfaChallenge(
            user_id=user_id,
            token_hash=hash_token(token),
            primary_method="password",
            expires_at=expires,
        )
        session.add(challenge)
        session.flush()
        session.add_all(
            [
                UserSession(
                    user_id=user_id,
                    token_hash=hash_token(token),
                    jti=uuid4().hex,
                    expires_at=expires,
                ),
                EmailVerificationToken(
                    user_id=user_id, token_hash=hash_token(token), expires_at=expires
                ),
                PasswordResetToken(
                    user_id=user_id, token_hash=hash_token(token), expires_at=expires
                ),
                UserMfaMethod(user_id=user_id, secret_encrypted="encrypted-test-payload"),
                UserMfaRecoveryCode(user_id=user_id, code_hash=hash_token(token)),
                UserOAuthAccount(user_id=user_id, provider="google", provider_subject="123"),
                UserWebAuthnCredential(
                    user_id=user_id,
                    credential_id=b"test-credential",
                    public_key=b"test-public-key",
                    name="Test key",
                ),
                WebAuthnChallenge(
                    user_id=user_id,
                    mfa_challenge_id=challenge.id,
                    token_hash=hash_token(token),
                    challenge=b"test-challenge",
                    purpose="authentication",
                    expires_at=expires,
                ),
                AuthAuditLog(actor_user_id=user_id, target_user_id=user_id, action="test"),
            ]
        )
        session.commit()
    with Session(auth_engine) as session:
        persisted = session.scalar(select(UserSession))
        assert persisted.token_hash == hash_token(token)
        assert persisted.token_hash != token
        assert persisted.family_id
        assert persisted.expires_at == expires
        session.execute(delete(User).where(User.id == user_id))
        session.commit()
        for table in Base.metadata.sorted_tables:
            if table.name == "auth_audit_logs":
                audit = session.scalar(select(AuthAuditLog))
                assert audit.actor_user_id is None and audit.target_user_id is None
            else:
                assert session.execute(select(table)).all() == []


def test_populated_auth_downgrade_refused(auth_engine):
    with Session(auth_engine) as session:
        session.add(User(email="keep@example.test"))
        session.commit()
    with pytest.raises(RuntimeError, match="Cannot discard"), auth_engine.begin() as connection:
        command.downgrade(auth_config(connection), "base")
    with Session(auth_engine) as session:
        assert session.scalar(select(User.email)) == "keep@example.test"
