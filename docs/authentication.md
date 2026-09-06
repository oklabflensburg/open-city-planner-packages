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
