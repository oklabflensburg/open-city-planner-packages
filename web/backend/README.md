# Read-only package API

`app/main.py` exposes the versioned `/api/v1` FastAPI routes. `app/repository.py`
loads `registry/modules/*.json` through the existing Registry loader and builds
a deterministic in-memory search index. `app/models.py` defines the Pydantic v2
API contracts.

The service has no database and no write route. Start it from the repository
root with:

```bash
uv run uvicorn web.backend.app.main:app --reload --port 8000
```

Set `PACKAGES_REGISTRY_SOURCE` only when a different read-only Registry source
directory is required.
