# Registry Service v2 read API (shadow)

This implements the read boundary of [ADR #44](adr/registry-service-v2.md) and
[#47](https://github.com/oklabflensburg/open-city-planner-packages/issues/47), on the
[#45 shadow database](registry-shadow-database.md). **Registry v1 JSON remains
production authority.** No deployment flag, production database, runtime consumer,
Nuxt client or static `/index.json` / `/modules/{id}.json` route changes here.

## Existing API audit and compatibility

Before this change, `web/backend/app/main.py` registered these GET routes:

| Routes | Existing contract / source |
| --- | --- |
| `/api/v1/packages` | `PackagePage`: items, total, limit, offset; default limit 24 |
| `/api/v1/packages/{id}` | `PackageDetail`, including latest release and inline history |
| `/api/v1/packages/{id}/versions` | Array of `PackageRelease` |
| `/api/v1/packages/{id}/versions/{version}` | `PackageRelease` |
| `/api/v1/publishers` | Array of `PublisherSummary`, including package/release counts |
| `/api/v1/publishers/{id}` | `PublisherDetail` with `packages` |
| `/api/v1/search` | `SearchResult` containing legacy package summaries; default limit 8 |
| `/api/v1/health` | `HealthResponse`: status, registry_schema=1, loaded package count |

`app/models.py` defines those DTOs. `RegistryRepository` in `app/repository.py`
loads and validates JSON through `scripts.registry.load_registry`, creating an
in-memory index. The cached `repository()` dependency retains that snapshot for
the process lifetime; the existing routes have no conditional ETag handling.
The shared Nuxt SSR/browser client in `web/frontend/app/lib/api.ts` consumes the
package, publisher and search contracts. Its callers and types stay unchanged.
There was no separate `app/api/` router or service hierarchy to reuse. The existing
routes now live on an `APIRouter` included by `create_app()`.

### Two explicit representations on the shared paths

ADR #44 both assigns `/api/v1/publishers` and `/api/v1/search` to v2 and requires
preserving their existing DTOs. Replacing the publisher array with a page, or
replacing package summaries with module summaries, would break Nuxt. Therefore:

- Default `Accept: application/json`, `*/*`, or no Accept header retains the
  existing JSON-backed publisher/search contracts, even in an enabled shadow app.
- Explicit `Accept: application/vnd.ocp.registry.v2+json` selects the **DB-backed
  v2 representation** on these three shared paths. Positive quality is required;
  an explicitly higher `application/json` quality selects the legacy contract.
- Shared responses carry `Vary: Accept`, including errors and 304s. OpenAPI
  documents each media type with its own concrete response schema.
- If v2 is disabled, requesting that vendor representation returns 406, never a
  successful legacy response disguised as v2. New `/modules` routes are absent.

A representation has exactly one source. No DB failure triggers a JSON fallback.
The package family always keeps its existing JSON source and DTOs in this PR.
Content negotiation is an additive contract boundary, not an `/api/v2` path or a
production authority switch. Future public read-trial exposure still requires the
ADR's publication freeze, final import and legacy adapter alignment; simply
turning on this shadow feature is **not** that cutover.

## Activation and lifecycle

Default production startup needs neither a database URL nor the `registry-db`
extra. The flag defaults to `false` and accepts `true`/`false` (case insensitive);
other values fail explicitly.

For a local, disposable shadow database, follow the migration/import instructions
in [registry-shadow-database.md](registry-shadow-database.md), then start:

```bash
export PACKAGES_REGISTRY_DATABASE_URL='postgresql+psycopg://registry_test@127.0.0.1:5432/registry_test'
export PACKAGES_REGISTRY_V2_API_ENABLED=true
uv run --extra registry-db uvicorn web.backend.app.main:app --port 8000
```

The enabled app requires valid PostgreSQL configuration at startup. An engine is
created once in application lifespan and disposed on shutdown. Connections are
opened by readiness/reads, allowing liveness during an outage. Pool checkout and
connection establishment have five-second timeouts. URLs, SQL parameters and
underlying database error messages are not exposed by error responses.

Every v2 request gets its own session and `REPEATABLE READ`, `READ ONLY`
transaction, established **before** the first statement. DTOs are materialized
inside that transaction. Session close rolls back and connection close returns
the connection to the pool; autoflush is disabled and no commit is performed.
There is no global session, ORM cache or retained DB snapshot. The app reads the
configured PostgreSQL directly, not a separately cached projection or replica.

The read path is `route → RegistryReadService → RegistryDatabaseRepository →
SQLAlchemy/PostgreSQL`. Routes contain no SQL. The existing repository provides
batched published-record queries; Pydantic projection is explicit in the service.
The read-only transaction is enforced by PostgreSQL even if an accidental write
were introduced into application code.

## GET endpoints

| Path | v2 response | Selection |
| --- | --- | --- |
| `/api/v1/modules` | `ModulePage` | JSON, enabled app |
| `/api/v1/modules/{id}` | `ModuleDetail` | JSON, enabled app |
| `/api/v1/modules/{id}/versions` | `VersionPage` | JSON, enabled app |
| `/api/v1/modules/{id}/versions/{version}` | `PublishedVersion` | JSON, enabled app |
| `/api/v1/modules/{id}/channels` | Channel → `{version, sha256}` map | JSON, enabled app |
| `/api/v1/publishers` | `PublisherPage` | Explicit v2 Accept header |
| `/api/v1/publishers/{id}` | `RegistryPublisherDetail` | Explicit v2 Accept header |
| `/api/v1/search?q=statistics` | `ModuleSearch` | Explicit v2 Accept header |
| `/health` | `{status: "ok"}` | Always available, no DB or JSON read |
| `/ready` | Status, PostgreSQL source, schema revision | Enabled app only |

```bash
curl 'http://localhost:8000/api/v1/modules?channel=stable&host=0.3.0&sdk=1.15.2&limit=10'
curl 'http://localhost:8000/api/v1/modules/statistics/versions/0.3.0'
curl -H 'Accept: application/vnd.ocp.registry.v2+json' \
  'http://localhost:8000/api/v1/publishers?limit=10&offset=0'
curl -H 'Accept: application/vnd.ocp.registry.v2+json' \
  'http://localhost:8000/api/v1/search?q=statistics'
```

`/docs` and `/openapi.json` describe the enabled app's concrete contracts. There
are no POST, PUT, PATCH or DELETE routes for metadata, publication or promotion.

## DTO semantics

`app/api/models_registry_v2.py` defines public DTOs independently of SQLAlchemy:

- `ModuleSummary` contains ID/name/description, publisher identity, classification,
  license, source repository, optional links, `version_count`, `channels` and
  nullable `stable_version`. Detail adds the paginated `versions_url`.
- `stable_version` is the current explicit `module_channels.stable` target, never
  a synonym for the highest or latest published version. Absent stable is null.
  Channels contain the pointer's version and artifact SHA-256.
- `PublishedVersion` contains module ID, exact version, bundle format,
  `historical_publication_channel`, artifact, source, host/SDK compatibility,
  exact dependency specifiers, nullable `published_at` and provenance. Moving a
  channel does not rewrite the historical label or immutable binding.
- Artifact `url` preserves `artifact_original_url` byte-for-byte as a string,
  including historical GitHub URLs. SHA-256, nullable `byte_size` and nullable
  `storage_locator` are separate fields; enriching storage metadata does not
  replace the old URL with a canonical Artifact Store URL.
- Source has repository, nullable tag and commit. Dependencies are a map of module
  ID to the exact stored specifier; this service performs no dependency resolution.
- Provenance includes nullable builder version/commit, host commit, reproducible,
  host contract status and environment. Historical unknowns remain null, including
  `reproducible`; null is not false. Unattached build/candidate evidence is excluded.
- Publishers expose ID, name and `module_count`; detail includes a paginated
  `modules` page. Only publishers/modules with published `module_versions` appear.
  Classification stays module-level, without invented publisher trust semantics.

The imported fixture has three modules and six versions: analysis-areas stable
1.5.3, search beta 0.1.0, statistics stable 0.3.0. Candidate-only statistics 0.4.0
is absent. These are integration expectations, not application constants.

## Pagination, ordering, filters and search

Pages contain `items`, `total`, `limit`, `offset`. Limit is 1–100, default 50;
search retains default 8 on its shared path. Offset is nonnegative. An offset
beyond total returns an empty page with the original total. Publisher detail uses
limit/offset for its nested modules page. Default legacy publisher responses
remain unpaginated; v2 pagination is selected with the media type above.

Modules sort by name ASC, ID ASC; publishers by name ASC, ID ASC. Versions use the
existing `scripts.registry.semver_key` descending, with exact version string ASC
for equal precedence (build-metadata ties). Thus 1.10.0 precedes 1.9.0, and numeric
prerelease identifiers are ordered correctly.

`/modules` accepts publisher ID, classification (`first-party` or
`reviewed-community`), channel (`stable`, `beta`, `nightly`), `host` and `sdk`.
Compatibility queries require complete SemVer values supported by the existing
`packaging.Version` evaluator; stored ranges are evaluated with `SpecifierSet`.
Packaging's prerelease membership rules apply. No raw SQL version-string parsing
or dependency resolution occurs.

**All version conditions must match the same version.** With a channel, only its
current pointer target is evaluated against both host and SDK. Without a channel,
one published version must satisfy both compatibility conditions. Unrelated
historical labels or another compatible release cannot satisfy a channel filter.
No matching records is a successful empty page; unknown enum values are errors.

Search is case insensitive over ID, name, description and publisher name, using
bound PostgreSQL `ILIKE` with escaped literal `%`/`_`/`!`. A nonblank query of at
most 200 characters is required. Ranking is exact ID, exact name, ID/name prefix,
ID/name substring, then description/publisher match. Ties use module ID ASC.
There is no new extension, index migration or fuzzy ranking dependency.

For this small registry, filtered module candidates and their version summaries
are batched, then compatibility/ranking/pagination run in Python. Version history
is fetched and sorted before slicing; dependencies are fetched for that page only.
Publisher aggregates are sorted in SQL and sliced in Python. **Response size is
bounded, total scan/memory cost is not**: it grows with matching modules/versions.
Before a large registry rollout, move plain pagination/ranking into SQL and add a
reviewed SemVer/compatibility indexing strategy. This is a documented shadow-scale
choice. Module list/detail uses three SELECTs regardless of page size; version
pages also use three, publisher list one, publisher detail four. No per-module or
per-version publisher/artifact/dependency query loop exists.

## Errors, health and caching

Missing published modules, versions or publishers return 404. Invalid pagination,
classification, channel, compatibility version, exact SemVer or search query
returns 422. Database connection/query failures return sanitized 503 JSON with
`detail: "Registry database unavailable"`; there is no JSON fallback.

`/health` is DB-independent liveness. `/api/v1/health` preserves the original JSON
health contract and source. `/ready` queries `alembic_version`, requiring the
expected head (`0045_registry_v2`); connection failure, a missing table or an
unexpected revision returns 503. The head is checked by integration tests against
Alembic. This check is **not** run on each metadata request, and readiness does not
replace the separate import parity/review gate.

All v2 metadata responses, including errors, carry `Cache-Control: no-cache`.
Successful representations hash the deterministic serialized DTO bytes with
SHA-256 into a quoted strong ETag. Matching `If-None-Match` (including weak
validators, lists or `*`) returns 304 without a body. Data is re-read in a fresh
transaction before validation; there is no process or five-minute cache.
Changes to represented pointers, counts, display metadata, artifacts or evidence
change their affected ETags; unrepresented changes need not. Shared paths include
`Vary: Accept` so caches cannot confuse legacy and v2 DTOs. ETag is exposed by the
existing local-development CORS configuration.

## Verification and remaining boundaries

`web/backend/db_tests/test_registry_api.py` uses real PostgreSQL 18.6. Each test
creates a disposable schema, runs Alembic and imports the v1 fixture before HTTP
requests. Coverage includes exact historical DTO parity, unknown provenance,
candidate exclusion, SemVer sorting, pagination, search, same-version filters,
channel/ETag changes, a concurrent commit between response queries, read-only
transactions, pool cleanup, query counts, errors, OpenAPI response validation,
media negotiation and unchanged legacy responses. Default backend tests also
block optional DB imports in a fresh process to verify JSON-only startup.

The existing `Registry PostgreSQL` workflow runs database integrity/import tests
and API tests, plus migration and import CLI round trips. Existing Registry,
artifact, Ansible, frontend, GitGuardian and deterministic build checks remain.

Runtime cutover: **no**. Registry v1 compatibility cutover: **no**. Production
writes/provisioning: **no**. Artifact publication, promotion, UI migration and
public-read-trial deployment remain separate work in #48/#49/#50 and the ADR gates.
