# Registry v1 compatibility from PostgreSQL

Issue #48 implements the read boundary in [ADR #44](adr/registry-service-v2.md).
**Merge != cutover.** Production defaults to the existing frozen-file-capable
Nginx routes. This change performs no production cutover, promotion, Registry
write, artifact publication or Nuxt migration. JSON remains the recovery authority
until the separately reviewed writer cutover in #49.

## Audited v1 contract

The contract oracle is `scripts/registry.py`, used by `scripts/build_registry.py`:

| Document | Exact fields |
| --- | --- |
| `index.json` | `schema_version: 1`, `modules` array |
| Index module | `id`, `name`, `publisher`, `classification`, `channels`, `metadata` |
| Publisher | `id`, `name` |
| Channels | Optional `stable`, `beta`, `nightly`; each contains exactly `version`, `sha256` |
| Module document | `schema_version: 1`, `id`, `name`, `publisher`, `classification`, `license`, `source_repository`, `versions` |
| Optional module fields | `description`, `homepage`, `documentation_url`, omitted when absent |
| Historical version | `version`, `channel`, `artifact`, `bundle_format_version`, `source_commit`, `requires`; optional `source_tag` |
| Artifact | Original `url`, `sha256` |
| Requirements | `host`, `sdk`, `modules` (dependency ID → version range) |

The closed schemas are `schema/registry-v1.schema.json` and
`schema/module-v1.schema.json`. Every generated document goes through existing
schema validation; v2 provenance, storage, timestamps, row IDs and channel tables
are never serialized. Existing validators also reject temporary Actions URLs.

`canonical_json` encodes UTF-8, sorts object keys, uses two-space indentation,
retains non-ASCII characters and appends exactly one newline. Module IDs in the
index are sorted. `build_index` selects the highest SemVer for each immutable
historical publication channel; build metadata does not affect precedence, and
Python's stable first-maximum selection retains the existing equal-precedence tie
behavior. The static generator's `canonical_module` sorts versions ascending by
SemVer. The #45 importer records that canonical order as `historical_order`.
The shared DB `project_v1()` now emits that stored order directly, including when
it differs from SemVer order; it never rewrites historical releases.

Baseline: Analysis Areas stable **1.5.3**, Search beta **0.1.0**, Statistics stable
**0.3.0**; three modules, six published releases. Statistics **0.4.0 is absent**.
Candidate provenance, unattached artifacts and modules without published versions
cannot appear in this projection. Source tags/commits, digests, URLs, optional
fields, requirements and historical channel labels survive unchanged.

Before activation, Nginx serves the two JSON paths from `current/dist` with
`Cache-Control: public, max-age=300` and its normal static ETag behavior. The
artifact regex separately serves `.ocp` files from the immutable Artifact Store
with a one-year immutable cache policy. `/api/` routes to FastAPI and `/` to the
existing frontend. Legacy `/api/v1/packages`, default search/publishers and Nuxt
retain their existing behavior. `/api/v1/modules` remains the separately enabled
#47 DB API; v1 compatibility does not implicitly enable it.

The pinned real OCP consumer (`.github/ocp-host-verifier.json`) uses
`ModuleRegistryClient.resolve()` to fetch the index then module metadata, validate
closed models and pointer/digest consistency, and choose a channel or exact
version. Download, bundle validation and the installer bind the digest, source,
manifest and host/SDK/dependency requirements. Installed-module startup is
independent of Registry availability. No consumer transport changes are required.

## DB boundary and failure semantics

`RegistryCompatibilityService.index()` and `.module(id)` use
`RegistryDatabaseRepository.project_v1()` and `channel_targets()`. The shared
projection batches modules/publishers, versions/artifacts and dependencies in
three queries. The index adds one channel query, plus one readiness query at the
HTTP boundary, independent of module count. Each response uses the #47
`REPEATABLE READ`, `READ ONLY` session convention; no process metadata cache is
used. Separate HTTP requests may observe different committed states.

`validate_v1_representability(modules, channel_targets)` is the reusable #49
preflight. It validates historical documents and compares exact channel sets,
versions **and digests** against `build_index`, then uses the verified DB targets
in the index. Both endpoints guard before responding, including before 304.
The function is read-only; #49 must call it within its own writer transaction.

| State | Result |
| --- | --- |
| Highest historical stable release equals stable pointer | Allowed |
| New immutable stable release and pointer advanced together | Allowed |
| Stable pointer rolled back below highest historical stable | 503, fail closed |
| Historical beta relabeled as current stable | 503, fail closed |
| Same historical release assigned to beta and stable | 503, fail closed |
| Missing/extra channel or mismatched digest | 503, fail closed |

Unknown published module: 404. Invalid kebab-case ID (including over 63 characters,
slashes or backslashes): 404; no filesystem path is constructed. Metadata has no
artifact handler. Only GET routes exist. Database outage, schema mismatch or
unrepresentable metadata: 503 with sanitized error text, never a static fallback.
`/health` remains DB-independent; `/ready` checks the same schema revision as the
compatibility endpoints. No credentials, DB URLs or SQL diagnostics are logged by
the compatibility error handlers.

Successful responses use `application/json`, `Cache-Control: no-cache` and a
quoted SHA-256 ETag of the canonical uncompressed response bytes. Conditional GET
supports strong/weak `If-None-Match`, validator lists and `*`, returning an empty
304 with the same validators. Changes to represented bytes change the ETag;
internal-only storage/provenance changes do not. A pointer change either accompanies
a representable release change or fails closed. There is no content negotiation
or new compression policy; Nginx may compress transport independently.

## Explicit activation

For an isolated backend/shadow listener:

```sh
uv sync --frozen --extra registry-db
# DATABASE_URL is supplied privately for a read-only DB role.
PACKAGES_REGISTRY_V1_DB_COMPAT_ENABLED=true \
  uv run --extra registry-db uvicorn web.backend.app.main:app --host 127.0.0.1 --port 8100
```

`PACKAGES_REGISTRY_DATABASE_URL` must use `postgresql+psycopg`. The v1 flag defaults
to false; an invalid flag fails startup. A DB URL alone changes no routes.
`PACKAGES_REGISTRY_V2_API_ENABLED` remains independent.

Ansible separates backend and public routing activation:

| Variables | Backend / public authority |
| --- | --- |
| Both false (default) | Existing backend; Nginx static JSON |
| `packages_registry_v1_db_compat_enabled: true`, routing false | DB compatibility on loopback; public JSON still static |
| Both true | Public JSON proxied exclusively to DB compatibility |

The routing flag is `packages_registry_v1_db_compat_routing_enabled`. Ansible rejects
routing activation without backend activation. The backend flag installs the
`registry-db` extra and adds a required external systemd `EnvironmentFile`, configured
by `packages_registry_database_environment_file` (default
`/etc/open-city-planner-packages/registry-db.env`). Operators provision this file
root-owned, mode 0600, with the read-only DB URL; credentials never enter generated
unit files or the repository. Missing environment files fail startup.

Set the two Ansible booleans explicitly; changing backend environment alone cannot
change Nginx authority. Both metadata locations disable proxy caching/error
interception/upstream retry and contain no `try_files` in DB mode. The distinct
`.ocp` location remains an Artifact Store alias in both modes.

## Verification and cutover runbook

1. **Prerequisites and reviewed evidence:** satisfy ADR phases 1–3 in staging:
   PostgreSQL 18.6/migration `0045_registry_v2`, a SELECT-only service role, health,
   backups and tested restore; verify retained historical artifact bytes under #46.
   Record source SHA, migration revision, counts, digests, routing revision and active
   authority. Unavailable historical bytes block activation. Verify the #47 API
   and any participating legacy adapters describe the same frozen snapshot.
2. **Freeze publication:** pause the Registry JSON publication/promotion workflow
   and record the final reviewed full SHA. Pin the static release/recovery files
   to this SHA. Do not allow any concurrent JSON or DB publication writer.
3. **Final import:** use the #45 import procedure with separate import credentials
   against the selected shadow/read-trial database, never the HTTP role:

   ```sh
   uv run --extra registry-db alembic -c web/backend/alembic.ini upgrade head
   uv run --extra registry-db python -m web.backend.app.registry_import_v1 \
     --registry-root /path/to/frozen-sha/registry --confirm-shadow-import
   ```

   Existing conflicting state fails; do not patch historical records to make parity
   pass. Recovery/reinitialization of shadow data is a separate reviewed operation.
4. **Parity:** switch to read-only credentials and verify all frozen bytes in one
   snapshot (nonzero exit on schema, pointer, file-set or byte mismatch):

   ```sh
   uv run --extra registry-db python -m web.backend.app.registry_verify_v1 \
     --dist /path/to/frozen-sha/dist
   ```

5. **Host and HTTP gates:** run the suites below against disposable PostgreSQL,
   including the pinned real Host. In staging, enable the loopback backend flag;
   verify `/health`, `/ready`, both JSON paths, 404, ETags/304, candidate exclusion
   and controlled DB-outage 503. Record byte comparisons against the frozen SHA.
   The synthetic installation fixture does not establish historical artifact
   availability; complete the separate #46 artifact gate before production approval.
6. **Explicit read cutover:** only after all recorded gates and review, enable the
   Ansible routing flag. Application deployment alone does not authorize this step.
   Preserve the publication freeze. No writer activation accompanies read routing.
7. **Public verification:** compare uncompressed public bodies with the frozen
   baseline, check channel targets, `no-cache`, matching ETags and 304; confirm
   `.ocp` download routes still use immutable storage and readiness stays green.
   Record evidence in the cutover ledger; never infer success from deployment alone.
8. **Rollback before #49:** disable DB compatibility **routing**, serving the same
   frozen static SHA. Keep the #47 API on the identical snapshot or revert its read
   trial too. Verify consistency before unfreezing the original JSON writer.
   This is an explicit authority switch, never an automatic per-request fallback.
9. **After #49 writes:** never switch to stale Git JSON. Pause promotions and recover
   the compatible service/DB with backup/replay. Exceptional static recovery needs
   a fresh verified DB export and coordinated writer freeze per the ADR.

## Reproducible test evidence

The `Registry PostgreSQL` CI job uses an isolated PostgreSQL **18.6** service. Each
integration test migrates a disposable schema. It imports Registry v1, checks
byte parity, historical order, candidate exclusion, channel guards, consistent
read-only snapshots, bounded queries, HTTP caching/errors and v2/legacy regressions.

```sh
# Both paths below point to local/disposable test resources only.
export PACKAGES_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://registry_test@127.0.0.1:5432/registry_test
export PACKAGES_REGISTRY_HOST_VERIFIER_ROOT=/path/to/pinned-host
uv run --extra registry-db pytest web/backend/db_tests
uv run --extra registry-db pytest deploy/ansible/tests
```

The Host checkout must match `.github/ocp-host-verifier.json` and have dependencies
installed with `uv sync --frozen --extra dev --no-editable` in `backend`. CI sets
this path unconditionally. Without it, only the three real Host bridge tests skip
locally; that is not sufficient cutover evidence. The bridge captures actual
FastAPI DB response bytes, invokes the unmodified real Host resolver, checks all
historical versions and a nonempty synthetic dependency, and reuses the Host's
bundle/installation helpers for a synthetic local artifact with install,
idempotence, enable/preflight and disable. No historical artifact is downloaded.
CI additionally runs unchanged Host Registry and installer suites.

The actual Nginx template is rendered and served over isolated loopback TLS in
both modes, checking metadata authority, cache/revalidation, propagated 503 despite
existing static files, and `.ocp` route separation. No test uses production DB,
artifact store, SSH or deployment credentials. No auto-merge is configured.
