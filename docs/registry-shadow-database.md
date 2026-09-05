# Registry v2 shadow database

This implements the data-model/import portion of [ADR #44](adr/registry-service-v2.md)
and [#45](https://github.com/oklabflensburg/open-city-planner-packages/issues/45).
**Shadow mode only: Registry v1 JSON remains the production authority.** Nothing
connects the running FastAPI API or Nuxt UI to PostgreSQL. No production database,
Artifact Store, public API or promotion operation is provisioned here.

## Stack and configuration

The audit found FastAPI/Pydantic DTOs, a JSON-backed in-memory repository and no ORM,
Alembic, database engine or settings convention. The optional `registry-db` extra
adds one ORM (SQLAlchemy 2), Psycopg 3 and Alembic. Default `uv sync --frozen` and
application startup need neither the extra nor a DB URL. DTOs remain separate from
ORM entities under `web/backend/app/db/`.

From the repository root:

```bash
uv sync --frozen --extra registry-db
export PACKAGES_REGISTRY_DATABASE_URL='postgresql+psycopg://localhost/ocp_registry_shadow'
uv run --extra registry-db alembic -c web/backend/alembic.ini upgrade head
uv run --extra registry-db alembic -c web/backend/alembic.ini current
uv run --extra registry-db alembic -c web/backend/alembic.ini check
```

Supply a dedicated, disposable development/shadow database and a PostgreSQL role
with schema DDL and data privileges. The example assumes local authentication;
provide credentials through your local environment or PostgreSQL authentication
configuration, never committed files. `PACKAGES_REGISTRY_DATABASE_URL` is required
only by explicit DB operations and accepts only `postgresql+psycopg`. There is no
fallback database or import-time connection. Engine creation hides SQL parameters;
the importer does not echo connection URLs or driver diagnostics.

Revision **`0045_registry_v2`** creates seven relational tables in the configured
PostgreSQL search path, plus Alembic's version table. Its explicit DDL is independent
of future ORM edits. There is no `create_all` runtime bootstrap. Migration tooling
follows [Alembic's environment/metadata convention](https://alembic.sqlalchemy.org/en/latest/tutorial.html).

## Schema and ownership

| Table | Identity / purpose |
| --- | --- |
| `publishers` | Exact publisher ID, name and operational timestamps |
| `modules` | Exact module ID, required publisher FK, original classification/license/source repository, display fields and optional links |
| `artifacts` | Surrogate ID, unique `(digest_algorithm, digest)`, nullable size/storage locator; no bytes |
| `build_provenance` | Append-only source identity and optional builder/Host/evidence fields; separate records permit later independent build attempts |
| `module_versions` | Composite PK `(module_id, version)`, artifact/provenance FKs, original artifact URL, immutable publication channel, compatibility and source identity |
| `module_channels` | Composite PK `(module_id, channel)` and FK `(module_id, version)` to the same module's version; positive revision and update time |
| `module_dependencies` | Composite PK `(owner_module_id, owner_version, dependency_module_id)`, composite owner FK and target Module FK; exact specifier |

All foreign keys use `ON DELETE RESTRICT`; no cascading deletion can erase Registry
history. Check constraints cover existing classification/channel values, SHA-256
algorithm and lowercase digest shape, source commit shape, nonempty required fields,
nonnegative size/order, positive channel revision, bundle format and stable versus
prerelease selection. Exact SemVer, URL policy and requirement validation reuse the
existing Registry validator at the repository/import boundary. Version strings are
never normalized or resolved into dependency versions.

`historical_publication_channel` retains the v1 release field. `ModuleChannel` is
the separate mutable pointer; the importer initializes it from existing `build_index`
semantics and never repairs a conflicting pointer. The schema permits future pointer
operations; #49 must enforce the ADR's temporary v1 representability restriction.
No channel-promotion method or approval/audit lifecycle is implemented here.

The original artifact URL belongs to `ModuleVersion.artifact_original_url`, separate
from a digest's nullable `storage_locator`. Reusing a digest does not replace another
version's URL. No bytes are read, downloaded, stored or rehashed. Historical sizes
and storage locators stay unknown; #46 owns storage validation and authority cutover.

`historical_order` records canonical v1 version order. Existing SemVer sorting ignores
build metadata, so equal-precedence strings retain source order; that tie-breaker
must survive relational storage to reproduce v1 index selection and canonical JSON.
It is not a publication timestamp or version normalization.

## Import and verification

```bash
uv run --extra registry-db python -m web.backend.app.registry_import_v1 \
  --registry-root registry/ --confirm-shadow-import
# Repeat to verify a no-op: inserted_versions must be 0 and v1_parity true.
uv run --extra registry-db python -m web.backend.app.registry_import_v1 \
  --registry-root registry/ --confirm-shadow-import
```

The flag acknowledges that the configured DB is shadow infrastructure; it cannot
automatically determine an operator's deployment environment. No workflow imports
into production. Use the CLI against an explicitly selected shadow DB only.

The importer validates the Registry envelope and `registry/modules/*.json` with the
existing loader before writes. It does not read `dist/` or `candidates/`. One explicit
transaction obtains an import-scoped PostgreSQL advisory lock and inserts/compares
publishers, modules, artifact references, source provenance, versions, dependencies
and channels. All modules exist before dependencies are added. Missing targets and
conflicting publisher names fail instead of inventing identities or dropping edges.

Before commit, internal `project_v1()` reconstruction must match canonical source
JSON and `channel_targets()` must match `build_index`. A failure rolls back the whole
import. These internal helpers are for verification, not the #48 compatibility API.
The PostgreSQL tests additionally compare canonical output with committed `dist/`.

At the current source baseline the report is:

| Entity | Count |
| --- | ---: |
| Publishers | 1 |
| Modules | 3 |
| Published versions | 6 |
| Dependencies | 2 |
| Artifact references | 6 |
| Source-provenance records | 6 |
| Channel pointers | 3 |

Initial channels are `analysis-areas stable → 1.5.3`, `search beta → 0.1.0` and
`statistics stable → 0.3.0`. These counts/targets are computed from source, not
hardcoded by the importer. Statistics 0.4.0 remains candidate evidence and is not
imported as either a version or build record by this CLI.

For each historical version, source repository/tag/commit are copied exactly into
source provenance; a missing source tag stays NULL. Builder version/commit, Host
commit, reproducibility, Host-contract status and environment evidence remain NULL,
not fabricated success/failure. `published_at` stays NULL. `imported_at`, `created_at`
and `updated_at` are operational DB timestamps, never claimed release dates.

## Sessions, idempotency and conflicts

`RegistryDatabaseRepository` takes a caller-owned SQLAlchemy Session. Use a
short-lived session/transaction for reads and an explicit `Session(engine)` plus
`session.begin()` for writes. Repository methods flush as needed and never commit.
Let exceptions escape the transaction context so it rolls back. No HTTP route
creates a DB session in this PR.

`insert_published_version()` currently accepts validated historical v1 metadata;
it is not a production promotion interface. It locks the owning Module row through
version/dependency insertion. An identical concurrent call waits, then returns a
no-op; any changed digest, URL, source tag/commit, bundle format, requirements,
dependencies, historical channel or evidence conflicts. It never moves a channel.
Future #49 adds reviewed artifact/evidence validation and the complete promotion
transaction around this boundary.

Inserts compare existing records rather than updating them. A repeated identical
import changes no rows, timestamps, pointers or sequence values. Concurrent creation
of a shared digest uses PostgreSQL
[`ON CONFLICT DO NOTHING`](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert)
followed by comparison; it never overwrites the winner. PostgreSQL may consume a
sequence value on a failed first insertion/race, but that is not a published record.

The importer is deliberately strict even about display changes: a changed existing
source row, removed version/module, rewritten dependency, altered pointer or newly
claimed provenance fails. To trial a different source snapshot, create a fresh shadow
DB and import it. This tool is not a synchronization writer or future promotion job.

ORM flush guards additionally reject changes/deletions to versions, dependencies
and provenance, artifact deletion/digest changes and protected module/publisher
identity changes. Privileged raw SQL/bulk writes bypass those application guards;
they are unsupported Registry mutation paths. Database constraints still enforce
relational integrity. This is application-level immutability, not DB trigger-based
protection against a database administrator.

## Real PostgreSQL tests and CI

Provide a separate disposable test database whose role can create/drop schemas:

```bash
export PACKAGES_REGISTRY_TEST_DATABASE_URL='postgresql+psycopg://localhost/ocp_registry_test'
uv run --extra registry-db pytest web/backend/db_tests
# Existing Registry/backend tests remain independent of PostgreSQL:
uv run pytest
```

The DB suite fails if its explicit URL is missing; it never silently switches to
SQLite or skips integrity checks. Each test creates a random schema, migrates it
and removes only that schema afterward. Local validation used **PostgreSQL 18.6**.
The separate `Registry PostgreSQL` workflow uses an ephemeral PostgreSQL 18.6 service
and runs migrations, real FK/unique/restrict/check constraints, rollback, concurrent
inserts, unknown provenance, canonical parity, idempotency and fail-closed conflicts.
It also exercises the migration/import CLIs. Existing Registry, artifact, Ansible
and frontend jobs remain intact; no production environment or deployment job is added.

## Resetting shadow state

Prefer creating another empty shadow database and importing a recorded source SHA.
Keep any needed report/export and the source Git SHA before discarding the old DB.
Do not run destructive reset commands against a shared or production database.

For an explicitly disposable shadow DB, the migration round trip is:

```bash
uv run --extra registry-db alembic -c web/backend/alembic.ini downgrade base
uv run --extra registry-db alembic -c web/backend/alembic.ini upgrade head
```

Downgrade **drops all seven Registry tables and their data** in the selected schema;
it does not restore data from Git or reset artifact storage. Upgrade only recreates
the schema; run the explicit importer afterward. The test suite exercises this
round trip on an empty isolated schema. No production backup/restore, provisioning,
Runtime-Cutover or ADR authority transition is performed by these commands in CI.
