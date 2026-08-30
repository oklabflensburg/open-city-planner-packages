import type {
  PackageDetail,
  PackageFilters,
  PackagePage,
  PackageRelease,
  PublisherDetail,
  PublisherSummary,
  SearchResult,
} from '~/types/api'

type Fetcher = <T>(
  url: string,
  options?: { query?: Record<string, unknown>; signal?: AbortSignal },
) => Promise<T>

export function createApiClient(fetcher: Fetcher, baseURL: string) {
  const endpoint = (path: string) => `${baseURL.replace(/\/$/, '')}/v1${path}`
  const compactQuery = (values: Record<string, unknown>) => Object.fromEntries(
    Object.entries(values).filter(([, value]) => value !== '' && value !== undefined),
  )
  return {
    packages: (filters: PackageFilters = {}) =>
      fetcher<PackagePage>(endpoint('/packages'), {
        query: compactQuery(filters as Record<string, unknown>),
      }),
    search: (q: string, limit = 8, signal?: AbortSignal) =>
      fetcher<SearchResult>(endpoint('/search'), { query: { q, limit }, signal }),
    package: (id: string) => fetcher<PackageDetail>(endpoint(`/packages/${encodeURIComponent(id)}`)),
    versions: (id: string) =>
      fetcher<PackageRelease[]>(endpoint(`/packages/${encodeURIComponent(id)}/versions`)),
    version: (id: string, version: string) =>
      fetcher<PackageRelease>(
        endpoint(`/packages/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}`),
      ),
    publishers: () => fetcher<PublisherSummary[]>(endpoint('/publishers')),
    publisher: (id: string) =>
      fetcher<PublisherDetail>(endpoint(`/publishers/${encodeURIComponent(id)}`)),
  }
}

export type ApiClient = ReturnType<typeof createApiClient>
