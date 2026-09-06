import type {
  Channels,
  PackageDetail,
  PackageFilters,
  PackagePage,
  PackageRelease,
  PublisherDetail,
  PublisherSummary,
  RegistryPage,
  SearchResult,
} from '~/types/api'

export const REGISTRY_MEDIA_TYPE = 'application/vnd.ocp.registry.v2+json'
type Fetcher = <T>(
  url: string,
  options?: {
    query?: Record<string, unknown>
    signal?: AbortSignal
    headers?: Record<string, string>
    cache?: RequestCache
  },
) => Promise<T>

// Collect runtime pages, never a build-time snapshot. Reject incomplete traversal.
export async function collectPages<T>(
  read: (offset: number) => Promise<RegistryPage<T>>,
): Promise<T[]> {
  const items: T[] = []
  let page: RegistryPage<T>
  let total: number | undefined
  const ids = new Set<string>()
  do {
    page = await read(items.length)
    if (total !== undefined && page.total !== total)
      throw new Error('Registry changed during pagination')
    total = page.total
    for (const item of page.items) {
      const id = (item as { id?: string })?.id
      if (id && ids.has(id))
        throw new Error('Registry changed during pagination')
      if (id) ids.add(id)
    }
    if (!page.items.length && items.length < page.total)
      throw new Error('Incomplete registry response')
    items.push(...page.items)
  } while (items.length < page.total)
  return items
}

function compareVersions(a: string | undefined, b: string | undefined): number {
  if (!a || !b) return a ? 1 : b ? -1 : 0
  const [ac, ap] = a.split('+')[0]!.split(/-(.+)/)
  const [bc, bp] = b.split('+')[0]!.split(/-(.+)/)
  const coreA = ac!.split('.').map(Number),
    coreB = bc!.split('.').map(Number)
  for (let i = 0; i < 3; i++) {
    const d = coreA[i]! - coreB[i]!
    if (d) return d
  }
  if (!ap || !bp) return ap ? -1 : bp ? 1 : 0
  const x = ap.split('.'),
    y = bp.split('.')
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if (x[i] === y[i]) continue
    if (x[i] === undefined || y[i] === undefined)
      return x[i] === undefined ? -1 : 1
    const xn = /^\d+$/.test(x[i]!),
      yn = /^\d+$/.test(y[i]!)
    return xn && yn
      ? Number(x[i]) - Number(y[i])
      : xn !== yn
        ? xn
          ? -1
          : 1
        : x[i]!.localeCompare(y[i]!)
  }
  return 0
}

export function createApiClient(fetcher: Fetcher, baseURL: string) {
  const endpoint = (path: string) => `${baseURL.replace(/\/$/, '')}/v1${path}`
  const get = <T>(
    path: string,
    query?: Record<string, unknown>,
    signal?: AbortSignal,
  ) =>
    fetcher<T>(endpoint(path), {
      headers: { Accept: REGISTRY_MEDIA_TYPE },
      cache: 'no-cache',
      ...(query
        ? {
            query: Object.fromEntries(
              Object.entries(query).filter(
                ([, v]) => v !== '' && v !== undefined,
              ),
            ),
          }
        : {}),
      ...(signal ? { signal } : {}),
    })
  const modules = (filters: Omit<PackageFilters, 'q' | 'sort'> = {}) =>
    get<PackagePage>('/modules', filters)
  const search = (q: string, limit = 8, signal?: AbortSignal, offset = 0) =>
    get<SearchResult>('/search', { q, limit, offset }, signal)
  return {
    modules,
    allModules: () => collectPages((offset) => modules({ limit: 100, offset })),
    // v2 search has no filter/sort arguments. Intersect API search matches with API-filtered
    // modules before pagination so discovery never silently ignores a selected filter.
    async packages(filters: PackageFilters = {}): Promise<PackagePage> {
      const {
        q,
        sort = 'relevance',
        limit = 12,
        offset = 0,
        ...criteria
      } = filters
      const query = q?.trim()
      if (!query && (sort === 'relevance' || sort === 'name'))
        return modules({ ...criteria, limit, offset })
      let items = await collectPages((start) =>
        query
          ? search(query, 100, undefined, start)
          : modules({ ...criteria, limit: 100, offset: start }),
      )
      if (query && Object.values(criteria).some(Boolean)) {
        const matching = new Set(
          (
            await collectPages((start) =>
              modules({ ...criteria, limit: 100, offset: start }),
            )
          ).map((m) => m.id),
        )
        items = items.filter((m) => matching.has(m.id))
      }
      if (sort !== 'relevance')
        items.sort(
          (a, b) =>
            (sort === 'version'
              ? compareVersions(
                  b.channels.stable?.version,
                  a.channels.stable?.version,
                )
              : sort === 'id'
                ? a.id.localeCompare(b.id)
                : a.name.localeCompare(b.name)) || a.id.localeCompare(b.id),
        )
      return {
        items: items.slice(offset, offset + limit),
        total: items.length,
        limit,
        offset,
      }
    },
    search,
    package: (id: string) =>
      get<PackageDetail>(`/modules/${encodeURIComponent(id)}`),
    versions: (id: string, offset = 0, limit = 50) =>
      get<RegistryPage<PackageRelease>>(
        `/modules/${encodeURIComponent(id)}/versions`,
        { limit, offset },
      ),
    version: (id: string, version: string) =>
      get<PackageRelease>(
        `/modules/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}`,
      ),
    channels: (id: string) =>
      get<Channels>(`/modules/${encodeURIComponent(id)}/channels`),
    publishers: () =>
      collectPages((offset) =>
        get<RegistryPage<PublisherSummary>>('/publishers', {
          limit: 100,
          offset,
        }),
      ),
    publisher: (id: string, offset = 0, limit = 50) =>
      get<PublisherDetail>(`/publishers/${encodeURIComponent(id)}`, {
        limit,
        offset,
      }),
  }
}
export type ApiClient = ReturnType<typeof createApiClient>
