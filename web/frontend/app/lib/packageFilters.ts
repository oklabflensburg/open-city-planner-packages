import type { Channel, Classification, PackageFilters } from '~/types/api'

function text(value: unknown) { return typeof value === 'string' ? value : '' }

export function packageFiltersFromQuery(query: Record<string, unknown>): PackageFilters {
  return {
    q: text(query.q),
    publisher: text(query.publisher),
    classification: text(query.classification) as Classification | '',
    channel: text(query.channel) as Channel | '',
    host: text(query.host),
    sdk: text(query.sdk),
    sort: (text(query.sort) as PackageFilters['sort']) || 'relevance',
    limit: 12,
    offset: Math.max(0, Number(text(query.offset)) || 0),
  }
}

export function packageFiltersToQuery(filters: PackageFilters) {
  return Object.fromEntries(
    Object.entries(filters)
      .filter(([key, value]) => value !== '' && value !== undefined && value !== 0 && value !== 12 && !(key === 'sort' && value === 'relevance'))
      .map(([key, value]) => [key, String(value)]),
  )
}
