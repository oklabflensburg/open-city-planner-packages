import { describe, expect, it, vi } from 'vitest'
import { collectPages, createApiClient, REGISTRY_MEDIA_TYPE } from '~/lib/api'
import { detail, page, release } from './fixtures'
import {
  apiErrorStatus,
  installCommand,
  publicationDate,
  repositoryLinks,
} from '~/lib/modulePresentation'

describe('Registry v2 client', () => {
  it('negotiates every shared endpoint centrally, disables stale cache reuse, and encodes paths', async () => {
    const fetcher = vi.fn().mockResolvedValue(page)
    const api = createApiClient(fetcher, '/api/')
    await api.modules({ publisher: '', limit: 12, offset: 0 })
    await api.package('statistics')
    await api.version('statistics', '0.4.0+build')
    await api.versions('statistics', 50)
    await api.channels('statistics')
    await api.search('statistics')
    await api.publishers()
    await api.publisher('oklabflensburg')
    expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
      '/api/v1/modules',
      '/api/v1/modules/statistics',
      '/api/v1/modules/statistics/versions/0.4.0%2Bbuild',
      '/api/v1/modules/statistics/versions',
      '/api/v1/modules/statistics/channels',
      '/api/v1/search',
      '/api/v1/publishers',
      '/api/v1/publishers/oklabflensburg',
    ])
    for (const [, options] of fetcher.mock.calls)
      expect(options).toMatchObject({
        headers: { Accept: REGISTRY_MEDIA_TYPE },
        cache: 'no-cache',
      })
    expect(fetcher.mock.calls[0]![1].query).toEqual({ limit: 12, offset: 0 })
  })
  it('collects all pages for complete module/version counts', async () => {
    const read = vi.fn(async (offset: number) => ({
      items: [{ ...detail, id: String(offset), version_count: offset + 1 }],
      total: 3,
      offset,
      limit: 1,
    }))
    const items = await collectPages(read)
    expect(items).toHaveLength(3)
    expect(items.reduce((sum, m) => sum + m.version_count, 0)).toBe(6)
    expect(read.mock.calls).toEqual([[0], [1], [2]])
  })
  it('rejects changing or duplicate pages instead of overcounting modules', async () => {
    const changed = vi
      .fn()
      .mockResolvedValueOnce({ ...page, total: 2 })
      .mockResolvedValueOnce({ ...page, total: 3 })
    await expect(collectPages(changed)).rejects.toThrow('Registry changed')
    await expect(
      collectPages(async () => ({ ...page, total: 2 })),
    ).rejects.toThrow('Registry changed')
  })
  it('rejects truncated pagination rather than fabricating complete totals', async () => {
    await expect(
      collectPages(async () => ({
        items: [],
        total: 8,
        limit: 100,
        offset: 0,
      })),
    ).rejects.toThrow('Incomplete')
  })
  it('intersects search and API filters before pagination', async () => {
    const fetcher = vi.fn(async (url: string) =>
      url.endsWith('/search')
        ? { ...page, items: [detail, { ...detail, id: 'other' }], total: 2 }
        : page,
    )
    const result = await createApiClient(fetcher, '/api').packages({
      q: 'statistics',
      host: '0.2.0',
      limit: 1,
      offset: 0,
    })
    expect(result.total).toBe(1)
    expect(result.items[0]!.id).toBe('statistics')
    expect(fetcher.mock.calls.map((c) => c[0])).toEqual([
      '/api/v1/search',
      '/api/v1/modules',
    ])
  })
  it('rereads channel movement without a retained registry snapshot', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(detail)
      .mockResolvedValueOnce({
        ...detail,
        channels: { stable: { version: '0.5.0', sha256: 'a'.repeat(64) } },
      })
    const api = createApiClient(fetcher, '/api')
    expect((await api.package('statistics')).channels.stable?.version).toBe(
      '0.4.0',
    )
    expect((await api.package('statistics')).channels.stable?.version).toBe(
      '0.5.0',
    )
  })
  it('pins both immutable version and SHA with the supported CLI', () => {
    expect(installCommand('statistics', release)).toContain('--version 0.4.0')
    expect(installCommand('statistics', release)).toContain(
      `--expected-sha256 ${release.artifact.sha256}`,
    )
    expect(installCommand('statistics')).toBe(
      'ocp module install-registry statistics',
    )
  })
  it('derives only safe generic GitHub links', () => {
    expect(repositoryLinks(detail.source_repository)).toMatchObject({
      issues: `${detail.source_repository}/issues`,
      releases: `${detail.source_repository}/releases`,
    })
    expect(
      repositoryLinks('https://github.com.evil.test/org/repo').issues,
    ).toBeUndefined()
    expect(
      repositoryLinks('https://github.com/org/repo/tree/main').issues,
    ).toBeUndefined()
    expect(repositoryLinks('javascript:alert(1)')).toEqual({})
  })
  it('preserves unknown dates and distinguishes missing modules from API failures', () => {
    expect(publicationDate(null)).toBe('Nicht verfügbar')
    expect(apiErrorStatus({ statusCode: 404 })).toBe(404)
    expect(apiErrorStatus({ statusCode: 503 })).toBe(503)
    expect(apiErrorStatus(new Error('network'))).toBe(503)
  })
})
