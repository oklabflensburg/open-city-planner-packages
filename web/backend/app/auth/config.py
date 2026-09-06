# Adapted from open-city-planner 2238e18 (AGPL-3.0-only).
from functools import lru_cache
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_JWT_SECRET = "development-only-change-me-32-bytes-minimum"
DEVELOPMENT_OAUTH_STATE_SECRET = "development-oauth-state-change-me-32-bytes"
DEVELOPMENT_MFA_RECOVERY_PEPPER = "development-recovery-pepper-change-me-32-bytes"
MINIMUM_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    app_environment: str = "development"
    app_base_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    jwt_secret_key: str = Field(
        default=DEVELOPMENT_JWT_SECRET,
        validation_alias=AliasChoices("AUTH_SECRET", "JWT_SECRET_KEY"),
        repr=False,
    )
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "http://localhost:8000"
    jwt_audience: str = "package-hub"
    oauth_state_secret: str = Field(default=DEVELOPMENT_OAUTH_STATE_SECRET, repr=False)
    mfa_recovery_pepper: str = Field(default=DEVELOPMENT_MFA_RECOVERY_PEPPER, repr=False)
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    refresh_token_reuse_grace_seconds: int = 5
    account_deletion_recent_auth_seconds: int = 600
    refresh_rate_limit_attempts: int = 30
    refresh_rate_limit_window_seconds: int = 60
    refresh_require_origin: bool = False
    email_verification_expire_hours: int = 24
    password_reset_expire_minutes: int = 60
    auth_access_cookie_name: str = "ocp_hub_access_token"
    auth_refresh_cookie_name: str = "ocp_hub_refresh_token"
    auth_csrf_cookie_name: str = "ocp_hub_csrf_token"
    auth_mfa_cookie_name: str = "ocp_hub_mfa_challenge"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_cookie_domain: str | None = None
    auth_cookie_path: str = "/"
    email_backend: str = "smtp"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = Field(default=None, repr=False)
    smtp_from_email: str = "noreply@example.org"
    smtp_from_name: str = "OK Lab Flensburg"
    smtp_use_tls: bool = True
    github_client_id: str | None = None
    github_client_secret: str | None = Field(default=None, repr=False)
    google_client_id: str | None = None
    google_client_secret: str | None = Field(default=None, repr=False)
    oauth_redirect_base_url: str | None = None
    auth_rate_limit_attempts: int = 8
    auth_rate_limit_window_seconds: int = 300
    auth_rate_limit_backend: str = "memory"
    rate_limit_fail_closed: bool = False
    rate_limit_memory_max_keys: int = Field(default=10000, ge=100, le=100000)
    trusted_proxies: str = ""
    mfa_encryption_key: str | None = Field(default=None, repr=False)
    mfa_challenge_expire_seconds: int = Field(default=300, ge=60, le=900)
    mfa_max_attempts: int = Field(default=5, ge=3, le=10)
    mfa_totp_issuer: str = "Package Hub - OK Lab Flensburg"
    mfa_totp_valid_window: int = Field(default=1, ge=0, le=1)
    mfa_recovery_code_count: int = Field(default=10, ge=8, le=20)
    mfa_setup_expire_seconds: int = Field(default=600, ge=300, le=1800)
    reauth_max_age_seconds: int = Field(default=600, ge=60, le=3600)
    require_mfa_for_superusers: bool = False
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "Package Hub OK Lab Flensburg"
    webauthn_origin: str = "http://localhost:3000"
    webauthn_challenge_expire_seconds: int = Field(default=300, ge=60, le=900)
    webauthn_timeout_ms: int = Field(default=60000, ge=15000, le=300000)
    redis_enabled: bool = False
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_connect_timeout: float = 2.0
    redis_socket_timeout: float = 2.0
    redis_max_connections: int = 40
    cache_prefix: str = "ocp-hub:auth"

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def production(self) -> bool:
        return self.app_environment.lower() == "production"

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [value.strip() for value in self.trusted_proxies.split(",") if value.strip()]

    def validate_security(self) -> None:
        if self.auth_cookie_samesite not in {"lax", "strict"}:
            raise RuntimeError("AUTH_COOKIE_SAMESITE must be lax or strict")
        if self.auth_cookie_path != "/":
            raise RuntimeError("AUTH_COOKIE_PATH must be / for SSR")
        if self.email_backend not in {"smtp", "console"}:
            raise RuntimeError("EMAIL_BACKEND must be smtp or console")
        if self.production and (self.email_backend != "smtp" or not self.smtp_host):
            raise RuntimeError("Production auth requires SMTP delivery")
        if self.production and (not self.smtp_use_tls or not self.mfa_encryption_key):
            raise RuntimeError("Production auth requires SMTP TLS and MFA encryption")
        if self.production and self.jwt_issuer == "http://localhost:8000":
            raise RuntimeError("Production auth requires its own JWT_ISSUER")
        for name, value in [
            ("API_BASE_URL", self.api_base_url),
            ("OAUTH_REDIRECT_BASE_URL", self.oauth_redirect_base_url),
        ]:
            if value is None:
                continue
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or (self.production and parsed.scheme != "https")
            ):
                raise RuntimeError(f"{name} must be an absolute trusted origin")
        for provider in ("github", "google"):
            if bool(getattr(self, f"{provider}_client_id")) != bool(
                getattr(self, f"{provider}_client_secret")
            ):
                raise RuntimeError(f"Configure both {provider} client fields or neither")
        if self.production and (
            self.jwt_secret_key == DEVELOPMENT_JWT_SECRET
            or len(self.jwt_secret_key.strip()) < MINIMUM_JWT_SECRET_LENGTH
        ):
            raise RuntimeError(
                "AUTH_SECRET must be configured with at least "
                f"{MINIMUM_JWT_SECRET_LENGTH} characters in production"
            )
        if self.production and self.jwt_algorithm != "HS256":
            raise RuntimeError("JWT_ALGORITHM must be HS256")
        separated_secrets = {self.jwt_secret_key, self.oauth_state_secret, self.mfa_recovery_pepper}
        if self.production and (
            len(self.oauth_state_secret.strip()) < MINIMUM_JWT_SECRET_LENGTH
            or self.oauth_state_secret == DEVELOPMENT_OAUTH_STATE_SECRET
        ):
            raise RuntimeError("OAUTH_STATE_SECRET must be configured securely in production")
        if self.production and (
            len(self.mfa_recovery_pepper.strip()) < MINIMUM_JWT_SECRET_LENGTH
            or self.mfa_recovery_pepper == DEVELOPMENT_MFA_RECOVERY_PEPPER
        ):
            raise RuntimeError("MFA_RECOVERY_PEPPER must be configured securely in production")
        if self.production and len(separated_secrets) != 3:
            raise RuntimeError("JWT, OAuth state and MFA recovery secrets must be distinct")
        if self.production and (not self.auth_cookie_secure):
            raise RuntimeError("AUTH_COOKIE_SECURE must be true in production")
        if self.production and (not self.refresh_require_origin):
            raise RuntimeError("REFRESH_REQUIRE_ORIGIN must be true in production")
        if self.auth_rate_limit_backend not in {"memory", "redis"}:
            raise RuntimeError("AUTH_RATE_LIMIT_BACKEND must be memory or redis")
        if self.production and self.auth_rate_limit_backend != "redis":
            raise RuntimeError("AUTH_RATE_LIMIT_BACKEND must be redis in production")
        if self.production and (not self.redis_enabled):
            raise RuntimeError("REDIS_ENABLED must be true in production")
        if self.production and (not self.rate_limit_fail_closed):
            raise RuntimeError("RATE_LIMIT_FAIL_CLOSED must be true in production")
        if self.mfa_encryption_key:
            try:
                Fernet(self.mfa_encryption_key.encode())
            except (TypeError, ValueError) as exc:
                raise RuntimeError("MFA_ENCRYPTION_KEY is invalid") from exc
        app_origin = urlsplit(self.app_base_url)
        if (
            app_origin.scheme not in {"http", "https"}
            or not app_origin.hostname
            or app_origin.username
            or app_origin.password
            or (app_origin.path not in {"", "/"})
            or app_origin.query
            or app_origin.fragment
        ):
            raise RuntimeError("APP_BASE_URL must be an absolute HTTP(S) origin without path")
        if self.production and app_origin.scheme != "https":
            raise RuntimeError("APP_BASE_URL must use HTTPS in production")
        if self.production and (not self.webauthn_origin.startswith("https://")):
            raise RuntimeError("WEBAUTHN_ORIGIN must use HTTPS in production")
        if "://" in self.webauthn_rp_id or "/" in self.webauthn_rp_id:
            raise RuntimeError("WEBAUTHN_RP_ID must be a hostname without scheme or path")
        origin = urlsplit(self.webauthn_origin)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username
            or origin.password
            or (origin.path not in {"", "/"})
            or origin.query
            or origin.fragment
        ):
            raise RuntimeError("WEBAUTHN_ORIGIN must be an HTTP(S) origin without path")
        rp_id = self.webauthn_rp_id.lower().rstrip(".")
        origin_host = origin.hostname.lower().rstrip(".")
        if origin_host != rp_id and (not origin_host.endswith(f".{rp_id}")):
            raise RuntimeError("WEBAUTHN_RP_ID must match the WebAuthn origin hostname")

    @property
    def configured_oauth_providers(self) -> list[str]:
        providers: list[str] = []
        if self.github_client_id and self.github_client_secret:
            providers.append("github")
        if self.google_client_id and self.google_client_secret:
            providers.append("google")
        return providers

    auth_database_url: str = Field(default="", repr=False)
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_security()
    return settings
