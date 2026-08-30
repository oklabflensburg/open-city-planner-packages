export type Classification = 'first-party' | 'reviewed-community'
export type Channel = 'stable' | 'beta' | 'nightly'

export interface Publisher { id: string; name: string }
export interface Compatibility { host: string; sdk: string; modules: Record<string, string> }
export interface Artifact { url: string; sha256: string }
export interface PackageRelease {
  version: string
  channel: Channel
  artifact: Artifact
  bundle_format_version: number
  source_commit: string
  source_tag?: string | null
  requires: Compatibility
}
export interface PackageSummary {
  id: string
  name: string
  description?: string | null
  publisher: Publisher
  classification: Classification
  latest_version: string
  latest_channel: Channel
  compatibility: Compatibility
  channels: Channel[]
}
export interface PackageDetail extends PackageSummary {
  source_repository: string
  license: string
  homepage?: string | null
  documentation_url?: string | null
  versions: PackageRelease[]
}
export interface PackagePage { items: PackageSummary[]; total: number; limit: number; offset: number }
export interface SearchResult extends PackagePage { query: string }
export interface PublisherSummary {
  id: string
  name: string
  classifications: Classification[]
  package_count: number
  release_count: number
}
export interface PublisherDetail extends PublisherSummary { packages: PackageSummary[] }
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
