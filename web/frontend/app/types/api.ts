export type Classification = 'first-party' | 'reviewed-community'
export type Channel = 'stable' | 'beta' | 'nightly'
export interface Publisher {
  id: string
  name: string
}
export interface ChannelTarget {
  version: string
  sha256: string
}
export type Channels = Partial<Record<Channel, ChannelTarget>>
export interface PackageSummary {
  id: string
  name: string
  description: string | null
  publisher: Publisher
  classification: Classification
  license: string
  source_repository: string
  homepage: string | null
  documentation_url: string | null
  stable_version: string | null
  channels: Channels
  version_count: number
}
export interface PackageDetail extends PackageSummary {
  versions_url: string
}
export interface PackageRelease {
  module_id: string
  version: string
  historical_publication_channel: Channel
  bundle_format_version: number
  artifact: {
    url: string
    sha256: string
    byte_size: number | null
    storage_locator: string | null
  }
  source: { repository: string; tag: string | null; commit: string }
  compatibility: { host: string; sdk: string }
  dependencies: Record<string, string>
  published_at: string | null
  provenance: {
    builder_version: string | null
    builder_commit: string | null
    host_commit: string | null
    reproducible: boolean | null
    host_contract_status: 'passed' | 'failed' | null
    environment: Record<string, unknown> | null
  }
}
export interface RegistryPage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}
export type PackagePage = RegistryPage<PackageSummary>
export interface SearchResult extends PackagePage {
  query: string
}
export interface PublisherSummary extends Publisher {
  module_count: number
}
export interface PublisherDetail extends PublisherSummary {
  modules: PackagePage
}
export interface PackageFilters {
  q?: string
  publisher?: string
  classification?: Classification | ''
  channel?: Channel | ''
  host?: string
  sdk?: string
  sort?: 'relevance' | 'name' | 'id' | 'version'
  limit?: number
  offset?: number
}
