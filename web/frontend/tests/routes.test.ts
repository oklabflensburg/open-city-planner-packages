import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const app = resolve(import.meta.dirname, '../app')

describe('required package explorer routes', () => {
  const pages = [
    'pages/index.vue',
    'pages/packages/index.vue',
    'pages/packages/[moduleId]/index.vue',
    'pages/packages/[moduleId]/[version].vue',
    'pages/publishers/index.vue',
    'pages/publishers/[publisherId].vue',
    'pages/about.vue',
    'pages/docs.vue',
  ]

  it.each(pages)('ships %s', (page) => {
    expect(existsSync(resolve(app, page))).toBe(true)
  })

  it('keeps every data-driven page on the central API client', () => {
    for (const page of pages.filter(page => !['pages/about.vue', 'pages/docs.vue'].includes(page))) {
      expect(readFileSync(resolve(app, page), 'utf8')).toContain('$api')
    }
  })

  it('configures SSR and canonical metadata', () => {
    const config = readFileSync(resolve(import.meta.dirname, '../nuxt.config.ts'), 'utf8')
    expect(config).toContain('ssr: true')
    expect(readFileSync(resolve(app, 'composables/usePageSeo.ts'), 'utf8')).toContain('canonical')
  })

  it('ships the search-first reusable explorer components', () => {
    for (const component of [
      'components/PackageListItem.vue',
      'components/SearchCommandPalette.vue',
      'components/SearchResultList.vue',
      'components/PackageMetadataRail.vue',
      'components/VersionSelector.vue',
      'components/CopyValue.vue',
      'components/KeyboardHint.vue',
    ]) expect(existsSync(resolve(app, component))).toBe(true)
  })
})
