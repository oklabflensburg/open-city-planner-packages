# Nuxt package explorer

The Nuxt 4 SSR application mirrors the supplied package-explorer design with a
navy header and hero, light content surfaces, green status actions, reusable
package/provenance/compatibility components and a mobile navigation layout.

All Registry data is fetched through `app/lib/api.ts`; components do not issue
ad-hoc `$fetch` calls. Runtime configuration uses
`NUXT_API_BASE_INTERNAL` for SSR and `NUXT_PUBLIC_API_BASE` in the browser.

```bash
pnpm install --frozen-lockfile
pnpm dev
pnpm typecheck
pnpm test
pnpm build
```
