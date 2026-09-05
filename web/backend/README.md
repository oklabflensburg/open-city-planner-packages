# Read-only package API

`app/main.py` exposes the versioned `/api/v1` FastAPI routes. `app/repository.py`
loads `registry/modules/*.json` through the existing Registry loader and builds
a deterministic in-memory search index. `app/models.py` defines the Pydantic v2
API contracts.

By default the service reads JSON and has no write route. Optional
[Registry v2 shadow database tooling](../../docs/registry-shadow-database.md) provides
PostgreSQL models, migrations and a separate v1 importer. The opt-in
[Registry v2 read API](../../docs/registry-api-v2.md) adds request-scoped PostgreSQL
reads at `/api/v1/modules` and explicitly negotiated publisher/search representations.
Enable `PACKAGES_REGISTRY_V2_API_ENABLED=true` with `PACKAGES_REGISTRY_DATABASE_URL`
and `uv run --extra registry-db` only for shadow/test operation. Legacy `/packages`
and default publisher/search contracts still read JSON; Registry v1 remains
production authority. `/health` is independent liveness; enabled `/ready` checks
PostgreSQL and its schema revision. No write or promotion API is exposed.

Start the default JSON API from the repository root with:

```bash
uv run uvicorn web.backend.app.main:app --reload --port 8000
```

Set `PACKAGES_REGISTRY_SOURCE` only when a different read-only Registry source
directory is required.
