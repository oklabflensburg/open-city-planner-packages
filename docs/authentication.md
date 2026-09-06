# Package Hub authentication

The implementation ports authentication from `oklabflensburg/open-city-planner`
at `2238e18e50348b04fcbbd4057e2dcbbd34ffa40c` (AGPL-3.0-only).
The supported external identities are GitHub and Google.

## Persistence (#63)

Auth uses the existing PostgreSQL infrastructure with a separate SQLAlchemy
metadata collection and Alembic history (`auth_alembic_version`). The Registry
history stays at `0049_promotions`; its readiness contract and all Registry tables
are unchanged. Auth tables provide no Registry publishing or promotion grants.
A separate database role must have access only to the auth tables.

Run migrations explicitly with a migration role against the intended database:

```sh
AUTH_DATABASE_URL=... uv run --extra registry-db alembic -c web/backend/auth_alembic.ini upgrade head
```

`AUTH_DATABASE_URL` is required and never falls back to the Registry credential.
Schema creation does not run during application startup. An empty auth schema can
be downgraded to `base`; a populated schema refuses destructive downgrade. For
rollback with account data, keep the schema and restore a compatible service.

The schema retains the reference's users, refresh session families, verification
and password reset tokens, encrypted TOTP methods, recovery code hashes, MFA
challenges, WebAuthn credentials and ceremonies. Only GitHub and Google are valid
OAuth providers. Identity ownership and one account per provider are enforced by
unique database constraints. Account emails are unique case-insensitively.

Account deletion cascades through credentials, sessions and challenges. Security
audit records remain with nullable actor/target references. The reference's city
administration audit model is scoped to authentication here. City planning tables,
marketing email state and provider instance registration are not included.

Refresh, verification and reset token records contain SHA-256 hashes, not bearer
tokens. The service layer will preserve reference session rotation/reuse handling,
keyed recovery code hashing and TOTP encryption. Database columns alone do not
supply those service-level guarantees. No auth routes or production activation are
introduced by the persistence commit.

Disposable PostgreSQL tests cover standalone migration, populated Registry
coexistence, upgrade/downgrade, model/schema parity, identity constraints, token
persistence, account deletion cascades and protection against destructive downgrade.

## Local authentication (#64)

Install the `auth` extra and explicitly set `AUTH_ENABLED=true` and
`AUTH_DATABASE_URL` to enable `/api/v1/auth` routes. The disabled application does
not import the auth dependency tree. It continues to serve the existing Registry.
`/health/auth` checks the independent schema revision and configured rate limiter;
it does not replace Registry readiness.

Local routes: signup, login, refresh, logout, logout-all, me, session, verify-email,
resend-verification, forgot-password, reset-password and change-password. Requests,
responses and error codes follow the reference. Passwords use Argon2 through
pwdlib; verification/reset tokens are single-purpose hashed database records.
Password reset/change revokes refresh sessions. Access JWTs retain the reference's
15-minute lifetime: revoking a refresh family does not invalidate already-issued
access JWTs. Disabled accounts are checked on every authenticated request.

Cookies are named `ocp_hub_access_token`, `ocp_hub_refresh_token` and
`ocp_hub_csrf_token`, avoiding collisions with the parent application. Access and
refresh cookies are HttpOnly; refresh is scoped to `/api/v1/auth`. The CSRF cookie
is readable by the browser for double-submit validation. Production requires
Secure cookies and a trusted Origin/Referer for refresh. Refresh rotation uses
row locks, a five-second concurrency grace period, and family revocation on reuse.
Auth responses are `no-store`; security rate limiting uses bounded memory only
for development and requires fail-closed Redis in production.

Security email text/templates and SMTP transport come from the reference, scoped
to verification, password and MFA notices. Database-managed email templates,
marketing messages and the city application's welcome outbox are not ported.
SMTP is the default transport. Explicit development `EMAIL_BACKEND=console`
logs only subject and size, never delivery links or bearer tokens. Tests intercept
mail in memory. Configured SMTP is required for actual email delivery.

## GitHub and Google (#65)

`GET /api/v1/auth/providers` and `/oauth/providers` expose only fully configured
providers, never credentials. Both providers share login/link/callback routes
under `/api/v1/auth/oauth/{provider}` and the reference identity service. Linking
requires a recent authenticated session, and the callback must still belong to
the initiating account. `/api/v1/users/me/oauth-accounts` lists links; DELETE on a
provider requires CSRF and recent authentication and protects the last login method.
Users can edit names through PATCH `/api/v1/users/me`.

Matching email addresses never auto-merge accounts. Provider emails are trusted
only when verified. Missing email creates a pending-email account, followed by
`POST /api/v1/auth/oauth/complete-email` and email verification. Identity and email
collisions are enforced in PostgreSQL, including concurrent account creation.

OAuth uses the reference HMAC-signed HttpOnly state cookie, validated local redirect
paths and provider-specific token/user-info exchanges. The Hub additionally checks
a signed issue timestamp server-side (600 seconds), closes token exchange clients,
and avoids exception details in exchange failure logs. The two reference central
provider flows do not use PKCE; no unrelated federated-provider flow was ported.
Production callbacks are the public origin followed by
`/api/v1/auth/oauth/github/callback` and `/api/v1/auth/oauth/google/callback`.

## MFA, passkeys and self-service (#66)

The reference MFA and WebAuthn services are ported, including Fernet-encrypted
TOTP secrets, last-counter replay prevention, HMAC recovery hashes, single-use
challenges, bounded attempts, expiry, row locking, security audit events and
recent-auth checks. Local and OAuth login do not issue a session until the
configured second factor succeeds. Recovery codes are displayed once and never
stored as plaintext. Enabling/changing MFA revokes other refresh sessions;
disabling MFA revokes all refresh sessions.

Routes cover `/auth/mfa/security`, `/auth/mfa/totp/setup`, `/auth/mfa/totp/confirm`,
`/auth/mfa/verify`, `/auth/mfa/challenge`, `/auth/mfa/recovery-codes`, DELETE
`/auth/mfa/totp`, and passkey registration, passwordless login, MFA and reauth
options/verification. `/users/me/passkeys` supports listing, renaming and removal.
WebAuthn verifies RP ID, origin, challenge, user verification and ceremony binding.
The reference's handling of synced credential counters is retained.

Account deactivation and deletion use the reference confirmation/password/recent
auth guards. Only auth data is affected; Registry tables have no user foreign keys
and remain untouched. Provider avatar metadata is retained in provider records;
no remote avatar fetch or city-specific avatar storage is introduced.
