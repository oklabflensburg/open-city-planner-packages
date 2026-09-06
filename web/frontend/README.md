# Open City Planner Package Hub

Nuxt 4.5.2 SSR, Vue 3 and Tailwind CSS 4. The supplied mockup defines the white
header, dark GIS hero, three-column module detail and footer. The logo and GIS
planes are repository-owned SVGs; there are no external image/font dependencies.

## Runtime data

`app/lib/api.ts` is the only Registry client. Modules and immutable versions use
`/api/v1/modules`; shared search and publisher endpoints always receive the
central `Accept: application/vnd.ocp.registry.v2+json` header. Configure
`NUXT_API_BASE_INTERNAL` for SSR and `NUXT_PUBLIC_API_BASE` for the browser.
The backend must enable `PACKAGES_REGISTRY_V2_API_ENABLED=true` and have a migrated,
populated PostgreSQL registry. A disabled/unavailable v2 API has no legacy fallback.

All metadata is fetched at runtime. There are no JSON registry imports, generated
Registry snapshots, prerendering, ISR or retained server-side Registry caches.
Fresh page requests resolve current channel pointers and then the matching immutable
version; a pointer/resource digest mismatch suppresses the download. HTML and API
requests require cache revalidation. An already-open tab is not a live subscription:
reload or revisit it to fetch a promotion. No frontend rebuild is needed.

Hero counts traverse all module pages, sum `version_count` and count distinct
publisher IDs. Incomplete or visibly changing pagination is an error. Open Source
is shown only when every returned license is an explicitly recognized open-source
SPDX identifier; unknown expressions produce “Nicht verfügbar”, not an estimate.
Search filters intersect complete v2 search results with complete API-filtered
module results before sorting/pagination. This is suitable for the current small
registry; large registries should add combined search/filter/aggregate support to
the read API rather than introduce a frontend registry cache.

## Validation

```bash
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
pnpm test:ssr
```

Run Nuxt commands sequentially: build, typecheck and the Nuxt test environment can
write the same generated directory. `test:ssr` starts the built application and an
isolated in-process fixture API. It verifies SSR metadata, media negotiation,
404/503 and pointer changes with the same running build. Fixtures under `tests/`
are test inputs only, captured from public v2 resources on 2026-09-05; they are never
imported by the application. `pnpm dev` starts local development.
