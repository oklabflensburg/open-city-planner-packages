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
refresh cookies are HttpOnly; the Hub scopes refresh to `/` for SSR (see below). The CSRF cookie
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

## SSR and browser UI (#67)

The Hub provides `/anmelden`, `/registrieren`, `/passwort-vergessen`,
`/passwort-zuruecksetzen`, `/email-bestaetigen`, `/profil`, `/auth/callback` and
`/auth/mfa`. The header reflects the authenticated user; unrelated header controls,
Registry views and footer services retain their existing behavior.

Unlike the reference's client-only bootstrap, SSR resolves `/auth/me` before
rendering. Only an explicit user projection enters the Nuxt payload. CSRF and MFA
challenges stay in browser cookies or request-local memory; recovery codes and
TOTP secrets exist only in the active client component. Nothing uses localStorage.
Email-token query URLs receive an empty 303 response to the same local path
with a browser-only fragment before SSR. This also protects error rendering during
outages. Nuxt `payload.path` is additionally stripped of email-token queries; the
browser consumes the token into component memory and replaces the URL after hydration.

The refresh cookie path is `/` in the Hub so Nuxt receives it on page requests and
can recover expired access sessions during SSR. It remains HttpOnly, Secure in
production, host-only by default, and protected by Origin/Referer validation on
refresh. Nuxt forwards cookies only to the configured internal API and propagates
rotated Set-Cookie headers to the browser. An uncertain SSR session causes a 503,
not an incorrectly anonymous header. Personalized responses and auth pages use
`private, no-store`; auth API responses use `no-store`.

Client refresh is single-flight and respects rotation conflicts. Auth generation
checks prevent an in-flight refresh from restoring a logged-out session. Refresh
failures explicitly return cookie deletions (FastAPI exception responses otherwise
discard modifications to the injected Response). Concurrent signup uniqueness
conflicts return the same 409 contract as sequential duplicates.

The browser test uses an isolated PostgreSQL schema, real backend and built SSR
server. It exercises signup, `/me`, SSR refresh, logout/login, protected profile,
actual signed WebAuthn registration/passwordless login/step-up with Chromium's
virtual authenticator, and token absence from HTML. It imports the checked-in
Registry into that disposable schema to verify personalized Registry-page caching.

```sh
uv sync --frozen --extra auth
# In web/frontend: pnpm install --frozen-lockfile; pnpm exec playwright install chromium; pnpm build
PACKAGES_REGISTRY_TEST_DATABASE_URL=... uv run --frozen --extra auth python -m scripts.run_auth_e2e
```

## Production activation and safety gates (#68)

Auth stays off by default (`packages_registry_auth_enabled: false`). Deployment
installs the frozen auth dependency extra, but does not create a database, run
migrations, provision a limiter/mail service, create secrets or activate providers.
Production inventory is unchanged.

Provision `/etc/open-city-planner-packages/auth.env` out of band, owned by root,
mode `0600` or `0400`, as a regular file, not a symlink. The backend's systemd
manager reads this file before dropping privileges. Frontend receives only
`NUXT_PUBLIC_AUTH_ENABLED` and its existing public/internal API origins. No
credential contents pass through Ansible variables, facts or `settings.json`.
Only the activation boolean and EnvironmentFile path use Registry deployment vars.
Secret-related preflight tasks are `no_log`.

Required production configuration:

- `AUTH_DATABASE_URL`: same PostgreSQL database, dedicated auth runtime role with
  CRUD grants on auth tables, SELECT on `auth_alembic_version`, and no Registry
  write privileges. Use a separate owner/migration role for schema changes.
- `APP_ENVIRONMENT=production`, `AUTH_ENABLED=true`, `APP_BASE_URL`, `API_BASE_URL`,
  `JWT_ISSUER`: `https://packages.stadtplaner.oklabflensburg.de`;
  `JWT_AUDIENCE=package-hub`.
- Independent random `AUTH_SECRET`, `OAUTH_STATE_SECRET`, `MFA_RECOVERY_PEPPER`
  (at least 32 characters each); `MFA_ENCRYPTION_KEY` generated with Fernet.
  Back up these securely; losing the encryption key prevents decrypting enrolled
  authenticators. Rotating JWT/recovery keys invalidates their existing credentials.
- `AUTH_COOKIE_SECURE=true`, `AUTH_COOKIE_SAMESITE=lax`,
  `REFRESH_REQUIRE_ORIGIN=true`; leave `AUTH_COOKIE_DOMAIN` unset for host-only
  cookies. `CORS_ORIGINS` contains the public HTTPS origin. `TRUSTED_PROXIES` must
  identify only the actual trusted proxy peer, typically `127.0.0.1/32` here.
- `WEBAUTHN_RP_ID=packages.stadtplaner.oklabflensburg.de`,
  `WEBAUTHN_ORIGIN=https://packages.stadtplaner.oklabflensburg.de` and an RP name.
- `EMAIL_BACKEND=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`,
  `SMTP_USE_TLS=true`, and the provider's `SMTP_USERNAME`/`SMTP_PASSWORD` if needed.
- `AUTH_RATE_LIMIT_BACKEND=redis`, `REDIS_ENABLED=true`, `REDIS_URL` for the existing
  service, `RATE_LIMIT_FAIL_CLOSED=true`. Use a dedicated `CACHE_PREFIX` per Hub
  environment.
- For each enabled provider, both `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET` or
  `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`. The callbacks are the public origin plus
  `/api/v1/auth/oauth/github/callback` and `/api/v1/auth/oauth/google/callback`.
  No provider credentials are required for local-only authentication.

Before activation, apply `auth_alembic` migrations with the migration role under
an operator-approved maintenance window, using the existing common lock file:
`/var/lib/ocp-packages-maintenance/maintenance.lock`. Acquire it with the same
nonblocking exclusive `flock` authority as deploy/retention. Never use a directory
lock or a second lock file. Migration is an explicit operator action; deployment
only verifies that it has already completed.

The preflight runs under systemd with the root EnvironmentFile, service user,
read-only filesystem and a read-only database transaction. It checks production
security settings, matching public/WebAuthn origin, auth revision/table grants,
absence of Registry write grants and limiter reachability. Activation additionally
requires `/health/auth` before proxy reload. Existing deployment lock, asynchronous
runner, immutable releases, artifact publication, Registry readiness, rollback and
retention behavior are retained. Rollback does not remove account data or downgrade
populated auth tables. No production operation was performed during implementation.

Auth URL access logs omit one-time query parameters: Uvicorn redacts auth query
strings; Nginx disables access logging only for auth-code and email-token routes.
These routes also use `no-referrer`. Other Registry logging remains unchanged.

CI adds an auth job with disposable PostgreSQL and virtual WebAuthn. Production
workflow eligibility depends on that job as well as the existing gates. Tests
never contact real OAuth providers or require production credentials.

## Validation report (2026-09-06)

All checks below used local disposable schemas/services or isolated provider mocks.

| Check | Result |
| --- | --- |
| Project backend, Registry DB, auth, workflow and Ansible tests | 627 passed; 4 optional Host tests initially skipped |
| Those 4 Host contract tests, rerun with pinned checkout `a0ec1edb1c904db18fea78aaffb531407e46f378` | 4 passed |
| Original pinned Host Registry/installer suites | 59 passed |
| Frontend Vitest suite | 49 passed |
| Built Registry SSR contracts | 5 passed |
| Browser auth/SSR/WebAuthn/email-token E2Es | 3 passed |
| Nuxt TypeScript check and production build | Passed |
| Ruff across repository | Passed |
| Ansible deploy playbook syntax check | Passed |
| `git diff --check` | Passed |

The previously skipped Host tests were all completed separately; no test remains
unverified because of that optional checkout. Test output includes an upstream
Starlette/httpx deprecation notice and Nuxt timing/instrumentation warnings.
Neither caused a failing check. Real OAuth providers, production SMTP/Redis and
production credentials were deliberately not exercised. Their activation remains
subject to the documented operator configuration and production preflight.

Changes are scoped to `web/backend/app/auth`, independent auth migrations/tests,
necessary `main.py` integration, frontend auth pages/components/SSR handling,
Ansible auth activation/privacy checks, CI and documentation. Registry models,
promotion, artifact building/publication, deployment lock/runner and retention
implementations are unchanged.
