import { mountSuspended } from '@nuxt/test-utils/runtime'
import { flushPromises } from '@vue/test-utils'
import { useNuxtApp, useRouter } from '#app'
import { describe, expect, it, vi } from 'vitest'
import AppHeader from '~/components/AppHeader.vue'
import AppFooter from '~/components/AppFooter.vue'
import DownloadCard from '~/components/DownloadCard.vue'
import GlobalPackageSearch from '~/components/GlobalPackageSearch.vue'
import PackageCard from '~/components/PackageCard.vue'
import PackageListItem from '~/components/PackageListItem.vue'
import SearchCommandPalette from '~/components/SearchCommandPalette.vue'
import { detail as pkg, release } from './fixtures'
import CopyValue from '~/components/CopyValue.vue'

describe('package explorer UI', () => {
  it('renders unavailable footer services without links, actions or focus targets', async () => {
    const wrapper = await mountSuspended(AppFooter)
    const services = wrapper.findAll('.social-links [aria-disabled="true"]')
    expect(services).toHaveLength(3)
    expect(services.map((service) => service.attributes('aria-label'))).toEqual(
      [
        'Bluesky – nicht verfügbar',
        'LinkedIn – nicht verfügbar',
        'RSS – nicht verfügbar',
      ],
    )
    for (const service of services) {
      expect(service.element.tagName).toBe('SPAN')
      expect(service.attributes('href')).toBeUndefined()
      expect(service.attributes('tabindex')).toBeUndefined()
      expect((service.element as HTMLElement).tabIndex).toBe(-1)
      expect(service.find('a, button, input, [tabindex]').exists()).toBe(false)
      expect(service.find('svg[aria-hidden="true"]').exists()).toBe(true)
    }
    expect(wrapper.findAll('.social-links a')).toHaveLength(1)
  })

  it('keeps unavailable header controls visible and disabled', async () => {
    const wrapper = await mountSuspended(AppHeader)
    expect(wrapper.findAll('.header-controls button')).toHaveLength(3)
    for (const button of wrapper.findAll('.header-controls button'))
      expect(button.attributes()).toHaveProperty('disabled')
  })
  it('copies the full digest and reports clipboard failures accessibly', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const wrapper = await mountSuspended(CopyValue, {
      props: {
        value: release.artifact.sha256,
        label: 'SHA-256',
        truncate: true,
      },
    })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(release.artifact.sha256)
    expect(wrapper.get('[role="status"]').text()).toBe('Kopiert')
    writeText.mockRejectedValueOnce(new Error('denied'))
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="status"]').text()).toContain(
      'Kopieren nicht möglich',
    )
  })
  it('renders a package card linked to the canonical detail route', async () => {
    const wrapper = await mountSuspended(PackageCard, { props: { pkg } })
    expect(wrapper.get('a').attributes('href')).toBe('/packages/statistics')
    expect(wrapper.text()).toContain('Statistics')
    expect(wrapper.text()).toContain('OK Lab Flensburg')
    expect(wrapper.text()).toContain('0.4.0')
  })

  it('renders a compact package result as a real canonical link', async () => {
    const wrapper = await mountSuspended(PackageListItem, {
      props: { pkg, showCompatibility: true },
    })
    expect(wrapper.get('a').attributes('href')).toBe('/packages/statistics')
    expect(wrapper.text()).toContain('statistics')
    expect(wrapper.text()).toContain('0.4.0')
  })

  it('uses the registry artifact URL directly for downloads', async () => {
    const wrapper = await mountSuspended(DownloadCard, {
      props: { moduleId: pkg.id, release },
    })
    const download = wrapper.get('a')
    expect(download.attributes('href')).toBe(release.artifact.url)
    expect(download.attributes()).toHaveProperty('download')
    expect(wrapper.text()).toContain('statistics-0.4.0.ocp')
    expect(wrapper.text()).toContain(release.artifact.sha256)
  })

  it('exposes an accessible mobile navigation toggle', async () => {
    const wrapper = await mountSuspended(AppHeader)
    const toggle = wrapper.get('button[aria-controls="mobile-menu"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('#mobile-menu').text()).toContain('Publisher')
  })

  it('queries the API and supports keyboard selection in global search', async () => {
    vi.useFakeTimers()
    const search = vi.fn().mockResolvedValue({
      items: [pkg],
      total: 1,
      limit: 8,
      offset: 0,
      query: 'analysis',
    })
    useNuxtApp().$api.search = search
    const wrapper = await mountSuspended(GlobalPackageSearch, {
      attachTo: document.body,
    })
    const input = wrapper.get('input')
    await input.setValue('analysis')
    await vi.advanceTimersByTimeAsync(161)
    await flushPromises()
    expect(search).toHaveBeenCalledWith('analysis', 8, expect.any(AbortSignal))
    expect(wrapper.get('[role="listbox"]').text()).toContain('Statistics')
    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.get('[role="option"]').attributes('aria-selected')).toBe(
      'true',
    )
    const push = vi.spyOn(useRouter(), 'push')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(push).toHaveBeenCalledWith('/packages/statistics')
    vi.useRealTimers()
  })

  it('focuses global search with slash and closes results with Escape', async () => {
    const wrapper = await mountSuspended(GlobalPackageSearch)
    const input = wrapper.get('input')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '/' }))
    await flushPromises()
    expect(document.activeElement?.id).toBe(input.attributes('id'))
    expect(input.attributes('aria-expanded')).toBe('true')
    await input.trigger('keydown', { key: 'Escape' })
    expect(input.attributes('aria-expanded')).toBe('false')
  })

  it('opens the command palette with Ctrl+K and closes it with Escape', async () => {
    const wrapper = await mountSuspended(SearchCommandPalette, {
      attachTo: document.body,
    })
    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }),
    )
    await flushPromises()
    expect(document.querySelector('[role="dialog"]')).not.toBeNull()
    const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).at(
      -1,
    )!
    const input = dialog.querySelector('input')!
    input.focus()
    input.dispatchEvent(
      new KeyboardEvent('keydown', {
        key: 'Tab',
        shiftKey: true,
        bubbles: true,
      }),
    )
    await flushPromises()
    const lastButton = Array.from(dialog.querySelectorAll('button')).at(-1)!
    expect(document.activeElement).toBe(lastButton)
    lastButton.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }),
    )
    await flushPromises()
    expect(document.activeElement).toBe(input)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    wrapper.unmount()
  })
})
