import { mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import { useNuxtApp } from '#app'
import { describe, expect, it, vi } from 'vitest'
import AppHeader from '~/components/AppHeader.vue'
import DownloadCard from '~/components/DownloadCard.vue'
import GlobalPackageSearch from '~/components/GlobalPackageSearch.vue'
import PackageCard from '~/components/PackageCard.vue'
import type { PackageRelease, PackageSummary } from '~/types/api'

const pkg: PackageSummary = {
  id: 'analysis-areas',
  name: 'Analysis Areas',
  description: 'Define and manage analysis areas for urban planning scenarios.',
  publisher: { id: 'oklabflensburg', name: 'OK Lab Flensburg' },
  classification: 'first-party',
  latest_version: '1.0.0',
  latest_channel: 'stable',
  compatibility: { host: '>=0.2.0,<1.0.0', sdk: '>=1.9.0,<2.0.0', modules: {} },
  channels: ['stable'],
}

const release: PackageRelease = {
  version: '1.0.0',
  channel: 'stable',
  artifact: {
    url: 'https://packages.example.test/modules/analysis-areas/1.0.0/analysis-areas-1.0.0.ocp',
    sha256: '7'.repeat(64),
  },
  bundle_format_version: 1,
  source_commit: 'a'.repeat(40),
  source_tag: 'v1.0.0',
  requires: pkg.compatibility,
}

describe('package explorer UI', () => {
  it('renders a package card linked to the canonical detail route', async () => {
    const wrapper = await mountSuspended(PackageCard, { props: { pkg } })
    expect(wrapper.get('a').attributes('href')).toBe('/packages/analysis-areas')
    expect(wrapper.text()).toContain('Analysis Areas')
    expect(wrapper.text()).toContain('OK Lab Flensburg')
    expect(wrapper.text()).toContain('1.0.0')
  })

  it('uses the registry artifact URL directly for downloads', async () => {
    const wrapper = await mountSuspended(DownloadCard, {
      props: { moduleId: pkg.id, release },
    })
    const download = wrapper.get('a')
    expect(download.attributes('href')).toBe(release.artifact.url)
    expect(download.attributes()).toHaveProperty('download')
    expect(wrapper.text()).toContain('analysis-areas-1.0.0.ocp')
    expect(wrapper.text()).toContain(release.artifact.sha256)
  })

  it('exposes an accessible mobile navigation toggle', async () => {
    const wrapper = await mountSuspended(AppHeader)
    const toggle = wrapper.get('button[aria-controls="mobile-menu"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('#mobile-menu').text()).toContain('Publishers')
  })

  it('queries the API and supports keyboard selection in global search', async () => {
    vi.useFakeTimers()
    const search = vi.fn().mockResolvedValue({ items: [pkg], total: 1, limit: 8, offset: 0, query: 'analysis' })
    useNuxtApp().$api.search = search
    const wrapper = await mountSuspended(GlobalPackageSearch)
    const input = wrapper.get('input')
    await input.setValue('analysis')
    await vi.advanceTimersByTimeAsync(221)
    await flushPromises()
    expect(search).toHaveBeenCalledWith('analysis')
    expect(wrapper.get('[role="listbox"]').text()).toContain('Analysis Areas')
    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.get('[role="option"]').attributes('aria-selected')).toBe('true')
    vi.useRealTimers()
  })
})
