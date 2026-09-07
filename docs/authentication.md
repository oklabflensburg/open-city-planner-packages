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
AUTH_DATABASE_URL='postgresql+asyncpg://auth_migration@127.0.0.1:5432/packages_dev' \
  uv run --extra auth alembic -c web/backend/auth_alembic.ini upgrade head
```

`AUTH_DATABASE_URL` is required and never falls back to the Registry credential.

Auth has one URL contract: `postgresql+asyncpg://` with a database name. The GitHub
secret `PACKAGES_AUTH_DATABASE_URL`, the generated `AUTH_DATABASE_URL` in `auth.env`
and local configuration all use that same form. Do not set the Auth runtime secret
to `postgresql+psycopg://` and do not create a second sync-URL secret.

| Consumer | Driver and configuration |
| --- | --- |
| Auth API runtime | `asyncpg==0.31.0`, SQLAlchemy `create_async_engine(auth_database_url(...))` |
| Auth Alembic and Production preflight | `psycopg[binary]==3.3.5`, `create_engine(auth_sync_database_url(...))` |
| Registry v1/v2 database | Unchanged `postgresql+psycopg://` through `PACKAGES_REGISTRY_DATABASE_URL` |

`web/backend/app/auth/db_config.py` validates the asyncpg URL independently of the
Registry parser. The sync helper uses SQLAlchemy's structured
`url.set(drivername="postgresql+psycopg")`; it preserves username, password, host,
port, database and query parameters without string replacement or manual credential
parsing. Invalid URLs produce fixed errors without credential contents.
The transport from GitHub through Ansible does not rewrite the URL.

Runtime connections use `timeout=5` and
`server_settings={"statement_timeout": "10000"}` with the existing pre-ping,
5-connection pool, 5 overflow connections and 10-second pool wait timeout. These are
[asyncpg connection parameters](https://magicstack.github.io/asyncpg/current/api/index.html#asyncpg.connection.connect)
passed through [SQLAlchemy's asyncpg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.asyncpg).
The synchronous preflight retains psycopg's `connect_timeout` and all existing
read-only schema/grant, Registry-write prohibition, Redis and origin checks.

The conversion preserves query parameters; it does not translate driver-specific
options. For example, asyncpg's `ssl` and libpq's `sslmode` are different connection
arguments. The documented local Production connection needs neither. Do not add
psycopg-only `options` to the runtime URL; set database-role defaults such as
`search_path` in PostgreSQL when needed by both drivers. Migration runs separately
with the migration/owner role, using the same URL format rather than runtime grants.

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

The browser test uses an isolated PostgreSQL database, real backend and built SSR
server. It exercises signup, `/me`, SSR refresh, logout/login, protected profile,
actual signed WebAuthn registration/passwordless login/step-up with Chromium's
virtual authenticator, and token absence from HTML. It imports the checked-in
Registry into that disposable database to verify personalized Registry-page caching.
The disposable test role needs CREATEDB permission; CI uses its isolated PostgreSQL
superuser. The launcher keeps Registry on psycopg and Auth on asyncpg without
passing psycopg-only search-path options to asyncpg.

```sh
uv sync --frozen --extra auth
# In web/frontend: pnpm install --frozen-lockfile; pnpm exec playwright install chromium; pnpm build
PACKAGES_REGISTRY_TEST_DATABASE_URL=... uv run --frozen --extra auth python -m scripts.run_auth_e2e
```

## Production activation and safety gates (#68, #70)

Auth stays off by default (`packages_registry_auth_enabled: false`). Deployment
installs the frozen auth dependency extra, but does not create a database, run
migrations, provision a limiter/mail service, create secrets or activate providers.
Production inventory is unchanged.

GitHub Environment `production` is the source of deployment inputs. The workflow
maps `vars.PACKAGES_REGISTRY_AUTH_ENABLED` to a JSON boolean
`packages_registry_auth_enabled`. Missing/empty or `false` stays disabled; only
`true` enables auth (case-insensitive). Other values fail without activating auth.
When disabled, secrets are neither required nor forwarded, the existing `auth.env`
is preserved, preflight is skipped, the backend omits its auth EnvironmentFile and
unsets `AUTH_ENABLED`, and the frontend receives `NUXT_PUBLIC_AUTH_ENABLED=false`.

The deployment pattern follows the reference
[Production workflow](https://github.com/oklabflensburg/open-city-planner/blob/main/.github/workflows/deploy.yml),
[builder](https://github.com/oklabflensburg/open-city-planner/blob/main/deploy/ansible/scripts/build-github-vars.py)
and [Vault example](https://github.com/oklabflensburg/open-city-planner/blob/main/deploy/ansible/vault.example.yml),
adapted to the Package Hub's asynchronous maintenance runner:

1. One workflow step exposes only explicitly mapped auth vars/secrets to
   `deploy/ansible/scripts/build-github-auth-vars.py`. The builder checks required
   inputs, provider pairs and control characters without logging values.
2. The builder creates a private temporary file (mode `0600` from creation), flushes
   and fsyncs it, then atomically replaces `${RUNNER_TEMP}/packages-auth-vars.json`.
   The workflow also applies `chmod 0600`. Unknown environment variables are ignored.
3. Ansible receives `--extra-vars "@${RUNNER_TEMP}/packages-auth-vars.json"`.
   Only the path is in the process arguments. No secret is passed through `-e key=value`.
4. The controller stages an explicit allowlist of `packages_auth_*` inputs into
   root-owned `auth-vars.json` (`0600`) inside the existing private invocation
   directory. The locked, asynchronous Ansible process reads it using a separate
   `--extra-vars @auth-vars.json`. This second hop is necessary because the Package
   Hub starts its deployment on the target under the process-owned `flock`.
5. After release preparation, Ansible validates runtime inputs, rejects symlinks in
   the file and all parent paths, and requires root-owned parents without group or
   other write access. It manages the immediate parent as `root:root`, mode `0755`,
   and atomically renders `packages-registry-auth.env.j2` to
   `/etc/open-city-planner-packages/auth.env` as `root:root`, mode `0600`.
   The existing stat checks and read-only Production preflight run before activation.
6. Runner cleanup uses `if: always()` to remove the JSON file, interrupted temporary
   files, SSH credentials and generated inventory. Remote invocation cleanup remains
   tied to confirmed async completion; SSH loss must not delete inputs still in use.
   Incomplete invocations remain root-private for operator inspection under the
   existing maintenance policy. The managed runtime file persists across deployments.

Secrets deliberately use `packages_auth_*`, outside the public
`packages_registry_*` namespace exported to `settings.json`. The only auth settings
in that public namespace are the activation boolean and runtime file path.
Secret copy, validation and rendering tasks use `no_log: true`; secret writes also
use `diff: false`. No secret values enter systemd unit files or frontend configuration.
The existing `registry-db.env` is independent and unchanged. Auth's systemd
EnvironmentFile is read by the root service manager before it drops privileges.

### GitHub production inputs

Set the **environment variable** `PACKAGES_REGISTRY_AUTH_ENABLED` only after the
prerequisites below are ready. The following **environment secrets** are supported:

| GitHub secret | Runtime environment key | Requirement |
| --- | --- | --- |
| `PACKAGES_AUTH_DATABASE_URL` | `AUTH_DATABASE_URL` | Required when enabled; `postgresql+asyncpg://` |
| `PACKAGES_AUTH_SECRET` | `AUTH_SECRET` | Required when enabled |
| `PACKAGES_AUTH_OAUTH_STATE_SECRET` | `OAUTH_STATE_SECRET` | Required when enabled |
| `PACKAGES_AUTH_MFA_RECOVERY_PEPPER` | `MFA_RECOVERY_PEPPER` | Required when enabled |
| `PACKAGES_AUTH_MFA_ENCRYPTION_KEY` | `MFA_ENCRYPTION_KEY` | Required when enabled |
| `PACKAGES_AUTH_REDIS_URL` | `REDIS_URL` | Required when enabled |
| `PACKAGES_AUTH_SMTP_HOST` | `SMTP_HOST` | Required when enabled |
| `PACKAGES_AUTH_SMTP_USERNAME` | `SMTP_USERNAME` | Optional |
| `PACKAGES_AUTH_SMTP_PASSWORD` | `SMTP_PASSWORD` | Optional |
| `PACKAGES_AUTH_SMTP_FROM_EMAIL` | `SMTP_FROM_EMAIL` | Required when enabled |
| `PACKAGES_AUTH_GITHUB_CLIENT_ID` | `GITHUB_CLIENT_ID` | Optional provider pair |
| `PACKAGES_AUTH_GITHUB_CLIENT_SECRET` | `GITHUB_CLIENT_SECRET` | Optional provider pair |
| `PACKAGES_AUTH_GOOGLE_CLIENT_ID` | `GOOGLE_CLIENT_ID` | Optional provider pair |
| `PACKAGES_AUTH_GOOGLE_CLIENT_SECRET` | `GOOGLE_CLIENT_SECRET` | Optional provider pair |

For either OAuth provider, both fields empty disables it, both supplied enables it,
and one supplied without the other fails before deployment. No Mastodon inputs are
introduced. SMTP without authentication is supported: the mail service calls
`smtp.login` only when `SMTP_USERNAME` is set. For authenticated SMTP supply the
credentials required by your relay; the template keeps TLS enabled on port 587.

Use the GitHub CLI's interactive secret prompt, which avoids secret values in shell
history and process arguments. These commands are operator instructions, not steps
run by this PR:

```bash
gh variable set PACKAGES_REGISTRY_AUTH_ENABLED --env production --body false \
  --repo oklabflensburg/open-city-planner-packages

# Each command prompts for its value. Skip optional values you do not use.
for name in \
  PACKAGES_AUTH_DATABASE_URL \
  PACKAGES_AUTH_SECRET \
  PACKAGES_AUTH_OAUTH_STATE_SECRET \
  PACKAGES_AUTH_MFA_RECOVERY_PEPPER \
  PACKAGES_AUTH_MFA_ENCRYPTION_KEY \
  PACKAGES_AUTH_REDIS_URL \
  PACKAGES_AUTH_SMTP_HOST \
  PACKAGES_AUTH_SMTP_USERNAME \
  PACKAGES_AUTH_SMTP_PASSWORD \
  PACKAGES_AUTH_SMTP_FROM_EMAIL \
  PACKAGES_AUTH_GITHUB_CLIENT_ID \
  PACKAGES_AUTH_GITHUB_CLIENT_SECRET \
  PACKAGES_AUTH_GOOGLE_CLIENT_ID \
  PACKAGES_AUTH_GOOGLE_CLIENT_SECRET
do
  gh secret set "$name" --env production \
    --repo oklabflensburg/open-city-planner-packages
done

# Enable only after completing the prerequisite sequence below.
gh variable set PACKAGES_REGISTRY_AUTH_ENABLED --env production --body true \
  --repo oklabflensburg/open-city-planner-packages
```

Stable security settings are deterministic Ansible values rather than GitHub secrets.
The HTTPS origins, CORS origin and WebAuthn RP ID derive from
`packages_registry_domain`. **`API_BASE_URL` is the bare HTTPS origin without `/api`**:
`web/backend/app/auth/config.py` rejects paths and `oauth.py` appends
`/api/v1/auth/oauth/{provider}/callback` itself. Using the issue's proposed `/api`
suffix would fail preflight and duplicate the callback path. `JWT_ISSUER` is
`https://<packages_registry_domain>/api`. Existing tokens issued under a different
issuer require users to sign in again.

### Activation sequence

1. Migrate the auth schema separately with the owner/migration role under the
   shared maintenance lock (see below).
2. Configure the dedicated auth runtime database role and grants, excluding all
   Registry write privileges.
3. Provide Redis for the security rate limiter.
4. Provide a TLS SMTP relay.
5. Set the required GitHub `production` secrets.
6. Optionally register GitHub OAuth and supply both GitHub fields.
7. Optionally register Google OAuth and supply both Google fields.
8. Set `PACKAGES_REGISTRY_AUTH_ENABLED=true` in GitHub Environment `production`.
9. Run the normal reviewed Production deployment. Updating a GitHub variable alone
   does not trigger a deploy; the existing workflow requires an application-changing
   push to `main` and all existing CI gates.
10. The deployment renders `auth.env`, checks ownership/mode and runs the existing
    Production preflight. Missing migrations, grants or Redis stop activation.
11. Require successful local auth/Registry health checks, TLS checks and public
    Registry smoke checks. Verify registration, verification email and any configured
    providers through the Package Hub after deployment.

No deployment step creates a database, runs `alembic upgrade head`, installs Redis
or configures SMTP. A failed preflight can leave the newly managed runtime file on
disk while the running services retain their previous environment until restart.
Release rollback does not restore old credentials; coordinate secret rotation and
back up keys independently of release rollback.

Required production configuration:

- `AUTH_DATABASE_URL`: same PostgreSQL database, dedicated auth runtime role with
  CRUD grants on auth tables, SELECT on `auth_alembic_version`, and no Registry
  write privileges. Use a separate owner/migration role for schema changes.
- `APP_ENVIRONMENT=production`, `AUTH_ENABLED=true`, `APP_BASE_URL`, `API_BASE_URL`,
  and `JWT_ISSUER` as described above;
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

## Asyncpg driver correction validation (2026-09-07)

The previous Auth runtime, Alembic and preflight reused the Registry URL validator,
which only accepts psycopg. Consequently the intended asyncpg Production URL failed
before connecting. Auth also lacked the asyncpg dependency and used psycopg-specific
connection arguments. The dedicated helper, asyncpg runtime and internally derived
psycopg maintenance URL resolve that driver mismatch without changing the Production
secret, Registry parser or Ansible transport.

Validation used a disposable PostgreSQL 18 container and the pinned real Host
checkout for Registry contract tests:

| Command | Result |
| --- | --- |
| `uv sync --frozen --extra auth` after `uv lock` | Passed |
| `uv run pytest web/backend/auth_tests` | 113 passed |
| `uv run pytest web/backend/db_tests` | 185 passed, including Host tests |
| `uv run pytest web/backend/tests` | 16 passed |
| `uv run pytest tests` | 233 passed |
| `uv run pytest deploy/ansible/tests` | 126 passed |
| Final preflight regression run with dedicated login-role URL | 19 passed |
| `uv run python -m scripts.run_auth_e2e` using the existing built frontend | 3 browser tests passed |
| `uv run ruff check .`, `git diff --check` | Passed |

The new tests cover credential-safe parse errors, driver rejection, lossless sync
URL derivation, unchanged Ansible transport, real asyncpg connections/sessions and
`statement_timeout=10s`. Alembic runs in a subprocess from an asyncpg environment URL
against a newly created empty database and reaches `0063_auth_persistence`.
The actual synchronous preflight DB checks accept an asyncpg URL for a dedicated
login role, reject a wrong revision and missing Auth grants, and still reject
Registry write grants. The existing Starlette/httpx deprecation warning remains.

No Frontend sources, GitHub secrets, Production database or Production services were
changed. No Production deploy was executed. These tests resolve the reported URL
validation failure; live connectivity, grants, schema and Redis remain subject to
the unchanged on-server preflight.

## Secret deployment validation (#70, 2026-09-07)

Previously, the Production workflow forwarded neither the auth activation flag nor
runtime secrets, so the `false` default persisted and Ansible expected a manually
provisioned EnvironmentFile. This change supplies both through the separate private
transport described above; it performs no Production operation.

| Check | Result |
| --- | --- |
| `uv run pytest deploy/ansible/tests tests web/backend/tests` | 373 passed |
| Final `uv run pytest deploy/ansible/tests/test_maintenance_lock.py deploy/ansible/tests/test_auth_secret_transport.py tests/test_workflow_contract.py` after adding complete-provider and enabled async-runner cases | 70 passed |
| `uv run --extra auth --extra registry-db pytest web/backend/auth_tests web/backend/db_tests` with disposable PostgreSQL 18 | 283 passed; 4 optional host tests initially skipped |
| `uv run pytest web/backend/db_tests/test_registry_host_contract.py` with the pinned Host checkout and disposable PostgreSQL | All 4 passed |
| `pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm test`, `pnpm build` in `web/frontend` | All passed |
| `pnpm test:ssr` against the built frontend | 5 passed |
| `uv run ruff check .` | Passed |
| `uv run ansible-playbook --syntax-check -i deploy/ansible/inventory/production.example.ini deploy/ansible/playbooks/deploy.yml` | Passed |
| `git diff --check` | Passed |
| Additional disposable-container Ansible check as root | 7 cases passed: actual root:root/0600, disabled preservation, missing secret, file symlink, parent symlink, writable parent, partial OAuth; no sentinel output |

The root-container check executed the real runtime tasks and the existing preflight
stat/security tasks, without starting systemd services. Committed regression tests
exercise both secret hops (including the actual asynchronous locked runner), the
real template and Production Settings validation, optional-provider behavior,
control-character rejection and sentinel absence from logs under `--diff`, public
settings and systemd units. Existing Starlette/httpx deprecation and frontend build
performance warnings do not fail these checks.

From these local tests the change is ready for CI and review. They do not attest to
live Production schema, grants, credentials, service reachability or TLS. Activation
still requires the documented prerequisites and successful on-server read-only
preflight and smoke checks. No GitHub Production input, Production database or
Production service was changed.

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
