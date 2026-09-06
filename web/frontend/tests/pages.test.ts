import { clearNuxtData, useNuxtApp } from '#app'
import { mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LandingPage from '~/pages/index.vue'
import PackageListPage from '~/pages/packages/index.vue'
import PackageDetailPage from '~/pages/packages/[moduleId]/index.vue'
import VersionDetailPage from '~/pages/packages/[moduleId]/[version].vue'
import PublishersPage from '~/pages/publishers/index.vue'
import {
  packageFiltersFromQuery,
  packageFiltersToQuery,
} from '~/lib/packageFilters'
import { detail, release, page, publisher } from './fixtures'

describe('DB-backed Package Hub pages', () => {
  beforeEach(() => {
    clearNuxtData()
    const api = useNuxtApp().$api
    api.modules = vi.fn().mockResolvedValue(page)
    api.allModules = vi.fn().mockResolvedValue([detail])
    api.packages = vi.fn().mockResolvedValue(page)
    api.publishers = vi.fn().mockResolvedValue([publisher])
    api.package = vi.fn().mockResolvedValue(detail)
    api.version = vi.fn().mockResolvedValue(release)
    api.versions = vi.fn().mockResolvedValue({ ...page, items: [release] })
  })
  it('renders the hero from complete API data', async () => {
    const wrapper = await mountSuspended(LandingPage, { route: '/' })
    expect(wrapper.text()).toContain('Module für offene')
    expect(wrapper.text()).toContain('Statistics')
    expect(wrapper.get('.hero-stats').text()).toContain('3Versionen')
  })
  it('renders discovery and preserves shareable filters', async () => {
    const wrapper = await mountSuspended(PackageListPage, {
      route: '/packages',
    })
    expect(wrapper.text()).toContain('1 Module gefunden')
    const query = {
      q: 'analysis',
      publisher: 'oklabflensburg',
      classification: 'first-party',
      channel: 'stable',
      host: '0.2.0',
      sdk: '1.9.0',
      sort: 'name',
    }
    expect(packageFiltersToQuery(packageFiltersFromQuery(query))).toEqual(query)
  })
  it.each([
    ['/packages', 'Keine Module gefunden'],
    ['/packages?q=unpublished', 'Keine Module gefunden für „unpublished“'],
  ])('renders a German empty state at %s', async (route, title) => {
    useNuxtApp().$api.packages = vi.fn().mockResolvedValue({
      ...page,
      items: [],
      total: 0,
    })
    const wrapper = await mountSuspended(PackageListPage, { route })
    expect(wrapper.get('.surface-card h2').text()).toBe(title)
    expect(wrapper.get('.surface-card p').text()).toBe(
      'Versuche einen anderen Suchbegriff oder entferne die Filter.',
    )
  })
  it('renders statistics 0.4.0 using explicit pointers, real license, digest, repository and empty states', async () => {
    const wrapper = await mountSuspended(PackageDetailPage, {
      route: '/packages/statistics',
    })
    expect(wrapper.get('.stable-number').text()).toBe('0.4.0')
    expect(wrapper.get('.license-card').text()).toContain('AGPL-3.0-only')
    expect(wrapper.get('.module-meta').text()).toContain('Nicht verfügbar')
    expect(wrapper.get('.module-meta').text()).not.toContain('September')
    expect(wrapper.get('a[download]').attributes('href')).toBe(
      release.artifact.url,
    )
    expect(wrapper.get('.stable-card').text()).toContain(
      release.artifact.sha256,
    )
    expect(
      wrapper
        .findAll('a')
        .some(
          (a) => a.attributes('href') === `${detail.source_repository}/issues`,
        ),
    ).toBe(true)
    expect(wrapper.text()).toContain('Keine weiteren Channels')
    expect(wrapper.text()).toContain('Keine Dokumentation hinterlegt')
    expect(wrapper.find('.module-layout > .module-navigation').exists()).toBe(
      true,
    )
    expect(wrapper.find('.module-layout > .module-content').exists()).toBe(true)
    expect(wrapper.find('.module-layout > .metadata-rail').exists()).toBe(true)
  })
  it('loads paginated versions and exposes provenance and reproducible installation', async () => {
    const wrapper = await mountSuspended(PackageDetailPage, {
      route: '/packages/statistics',
    })
    await wrapper.get('#module-tab-1').trigger('click')
    await flushPromises()
    expect(useNuxtApp().$api.versions).toHaveBeenCalledWith('statistics', 0)
    expect(wrapper.get('#module-panel').text()).toContain('Reproducibility')
    expect(wrapper.get('#module-panel').text()).toContain(release.source.commit)
    await wrapper.get('#module-tab-2').trigger('click')
    expect(wrapper.get('#module-panel').text()).toContain('--version 0.4.0')
    expect(wrapper.get('#module-panel').text()).toContain(
      `--expected-sha256 ${release.artifact.sha256}`,
    )
    await wrapper.get('#module-tab-2').trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.get('#module-tab-3').attributes('aria-selected')).toBe(
      'true',
    )
    expect(wrapper.get('#module-panel').text()).toContain(
      'Keine Konfigurationsdokumentation',
    )
  })
  it('renders only real additional channels and does not select a beta as stable', async () => {
    useNuxtApp().$api.package = vi
      .fn()
      .mockResolvedValue({
        ...detail,
        stable_version: null,
        channels: { beta: { version: '0.5.0-beta.1', sha256: 'b'.repeat(64) } },
      })
    const wrapper = await mountSuspended(PackageDetailPage, {
      route: '/packages/statistics',
    })
    expect(wrapper.find('.stable-number').exists()).toBe(false)
    expect(wrapper.text()).toContain('Keine Stable-Version veröffentlicht')
    expect(wrapper.text()).toContain('0.5.0-beta.1')
    expect(useNuxtApp().$api.version).not.toHaveBeenCalled()
  })
  it('does not show a download if the version digest disagrees with its pointer', async () => {
    useNuxtApp().$api.version = vi
      .fn()
      .mockResolvedValue({
        ...release,
        artifact: { ...release.artifact, sha256: 'a'.repeat(64) },
      })
    const wrapper = await mountSuspended(PackageDetailPage, {
      route: '/packages/statistics',
    })
    expect(wrapper.find('a[download]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Stable-Versionsdaten nicht verfügbar')
  })
  it('renders immutable version detail and publisher aggregation', async () => {
    const version = await mountSuspended(VersionDetailPage, {
      route: '/packages/statistics/0.4.0',
    })
    expect(version.text()).toContain('Statistics 0.4.0')
    expect(version.text()).toContain(release.artifact.sha256)
    const publishers = await mountSuspended(PublishersPage, {
      route: '/publishers',
    })
    expect(publishers.text()).toContain('OK Lab Flensburg')
  })
  it('reports list API errors without fake results', async () => {
    useNuxtApp().$api.packages = vi
      .fn()
      .mockRejectedValue(new Error('unavailable'))
    const wrapper = await mountSuspended(PackageListPage, {
      route: '/packages',
    })
    expect(wrapper.text()).toContain('Modulsuche derzeit nicht verfügbar')
    expect(wrapper.find('.package-result').exists()).toBe(false)
  })
})
