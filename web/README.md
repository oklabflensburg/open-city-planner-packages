# Package Hub

The public application reads the PostgreSQL-backed Registry API:

```text
Nuxt SSR / Browser → Registry API → PostgreSQL Registry
```

`frontend/` contains Nuxt 4, Vue 3, Tailwind CSS 4 and TypeScript. Its central API
client negotiates Registry v2 for shared search/publisher routes and reads explicit
channel targets and immutable versions. Legacy endpoints remain for existing
consumers; the Package Hub does not use them as its data source.

## Local development

Install locked dependencies with `uv sync --frozen --extra registry-db` and
`pnpm install --frozen-lockfile` in `web/frontend`. See
[Registry v2](../docs/registry-api-v2.md) for local database setup. Start the API
with the v2 flag and a configured local `PACKAGES_REGISTRY_DATABASE_URL`:

```bash
PACKAGES_REGISTRY_V2_API_ENABLED=true uv run --extra registry-db uvicorn web.backend.app.main:app --reload --port 8000
```

Run `pnpm dev` in `web/frontend`. The browser API defaults to
`http://localhost:8000/api`; SSR uses `http://127.0.0.1:8000/api`. Override them with
`NUXT_PUBLIC_API_BASE` and `NUXT_API_BASE_INTERNAL`. Validation and runtime behavior
are documented in [frontend/README.md](frontend/README.md).

## Production

Nginx proxies `/` to Nuxt and `/api/` to FastAPI. Existing `/index.json`, module
JSON and immutable artifact routes remain compatible. Both application processes
run unprivileged from the immutable release directory. Explicit API activation and
DB runtime installation are described in
[the Ansible documentation](../deploy/ansible/README.md).
