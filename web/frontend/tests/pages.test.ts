import { clearNuxtData, useNuxtApp } from '#app'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LandingPage from '~/pages/index.vue'
import PackageListPage from '~/pages/packages/index.vue'
import PackageDetailPage from '~/pages/packages/[moduleId]/index.vue'
import VersionDetailPage from '~/pages/packages/[moduleId]/[version].vue'
import PublishersPage from '~/pages/publishers/index.vue'
import { packageFiltersFromQuery, packageFiltersToQuery } from '~/lib/packageFilters'
import type { PackageDetail, PackageRelease, PackageSummary } from '~/types/api'

const release: PackageRelease = {
  version: '1.0.0', channel: 'stable',
  artifact: { url: 'https://packages.example.test/analysis-areas-1.0.0.ocp', sha256: '7'.repeat(64) },
  bundle_format_version: 1, source_commit: 'a'.repeat(40), source_tag: 'v1.0.0',
  requires: { host: '>=0.2.0,<1.0.0', sdk: '>=1.9.0,<2.0.0', modules: {} },
}
const summary: PackageSummary = {
  id: 'analysis-areas', name: 'Analysis Areas', description: 'Urban analysis areas.',
  publisher: { id: 'oklabflensburg', name: 'OK Lab Flensburg' }, classification: 'first-party',
  latest_version: release.version, latest_channel: release.channel,
  compatibility: release.requires, channels: ['stable'],
}
const detail: PackageDetail = {
  ...summary, source_repository: 'https://github.com/oklabflensburg/analysis-areas',
  license: 'AGPL-3.0-or-later', documentation_url: 'https://example.test/docs', versions: [release],
}

describe('data-backed pages', () => {
  beforeEach(() => {
    clearNuxtData()
    const api = useNuxtApp().$api
    api.packages = vi.fn().mockResolvedValue({ items: [summary], total: 1, limit: 12, offset: 0 })
    api.publishers = vi.fn().mockResolvedValue([{
      id: 'oklabflensburg', name: 'OK Lab Flensburg', classifications: ['first-party'],
      package_count: 1, release_count: 1,
    }])
    api.package = vi.fn().mockResolvedValue(detail)
    api.version = vi.fn().mockResolvedValue(release)
  })

  it('renders the landing page from API data', async () => {
    const wrapper = await mountSuspended(LandingPage, { route: '/' })
    expect(wrapper.text()).toContain('Find verified modules')
    expect(wrapper.text()).toContain('Analysis Areas')
  })

  it('renders the searchable package list', async () => {
    const wrapper = await mountSuspended(PackageListPage, { route: '/packages' })
    expect(wrapper.text()).toContain('1 packages found')
    expect(wrapper.text()).toContain('Analysis Areas')
  })

  it('renders package detail and its Registry download', async () => {
    const wrapper = await mountSuspended(PackageDetailPage, { route: '/packages/analysis-areas' })
    expect(wrapper.text()).toContain('Provenance')
    expect(wrapper.get('a[download]').attributes('href')).toBe(release.artifact.url)
  })

  it('renders version detail compatibility and artifact data', async () => {
    const wrapper = await mountSuspended(VersionDetailPage, { route: '/packages/analysis-areas/1.0.0' })
    expect(wrapper.text()).toContain('Analysis Areas 1.0.0')
    expect(wrapper.text()).toContain('bundle v1')
    expect(wrapper.text()).toContain(release.artifact.sha256)
  })

  it('loads every package filter from the shareable URL', async () => {
    const filters = packageFiltersFromQuery({
      q: 'analysis', publisher: 'oklabflensburg', classification: 'first-party',
      channel: 'stable', host: '0.2.0', sdk: '1.9.0', sort: 'name',
    })
    expect(filters).toEqual(expect.objectContaining({
      q: 'analysis', publisher: 'oklabflensburg', classification: 'first-party',
      channel: 'stable', host: '0.2.0', sdk: '1.9.0', sort: 'name',
    }))
    expect(packageFiltersToQuery(filters)).toEqual({
      q: 'analysis', publisher: 'oklabflensburg', classification: 'first-party',
      channel: 'stable', host: '0.2.0', sdk: '1.9.0', sort: 'name',
    })
  })

  it('renders aggregated publishers without invented downloads', async () => {
    const wrapper = await mountSuspended(PublishersPage, { route: '/publishers' })
    expect(wrapper.text()).toContain('OK Lab Flensburg')
    expect(wrapper.text()).not.toContain('Downloads')
  })
})
