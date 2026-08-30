# Package explorer

The public web application keeps Registry v1 authoritative:

```text
registry/modules/*.json → read-only FastAPI API → Nuxt SSR explorer
```

`backend/` contains the FastAPI application, Pydantic v2 response contracts and
an in-memory repository/search layer. It uses the existing Registry loader and
never writes Registry metadata. `frontend/` contains the Nuxt 4, Vue 3,
Tailwind CSS 4 and TypeScript application. All data access goes through its
central API client.

## Local development

Install the locked dependencies from the repository root:

```bash
uv sync --frozen
cd web/frontend
pnpm install --frozen-lockfile
```

Run the API from the repository root:

```bash
uv run uvicorn web.backend.app.main:app --reload --port 8000
```

In another terminal, run the frontend:

```bash
cd web/frontend
pnpm dev
```

The local browser API base defaults to `http://localhost:8000/api`; SSR uses
`http://127.0.0.1:8000/api`. Override them with `NUXT_PUBLIC_API_BASE` and
`NUXT_API_BASE_INTERNAL` respectively.

## Validation

```bash
uv run ruff check .
uv run pytest
cd web/frontend
pnpm typecheck
pnpm test
pnpm build
```

## Production routing

Nginx preserves the Registry v1 URLs and routes the application separately:

```text
/                          Nuxt SSR
/api/                      FastAPI
/index.json                static Registry index
/modules/*.json            static Registry metadata
/modules/.../*.ocp         immutable artifact mirror
```

Both application processes run unprivileged under systemd and read the same
immutable `releases/<git-sha>` directory selected by the existing atomic
`current` symlink. Deployment details are in
[deploy/ansible/README.md](../deploy/ansible/README.md).
