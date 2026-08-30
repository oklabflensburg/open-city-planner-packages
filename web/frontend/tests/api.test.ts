import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from '~/lib/api'

describe('API client', () => {
  it('omits empty optional filters from package requests', async () => {
    const fetcher = vi.fn().mockResolvedValue({ items: [], total: 0, limit: 12, offset: 0 })
    const api = createApiClient(fetcher, '/api')

    await api.packages({
      q: '',
      publisher: '',
      classification: '',
      channel: '',
      host: '',
      sdk: '',
      sort: 'relevance',
      limit: 12,
      offset: 0,
    })

    expect(fetcher).toHaveBeenCalledWith('/api/v1/packages', {
      query: { sort: 'relevance', limit: 12, offset: 0 },
    })
  })
})
