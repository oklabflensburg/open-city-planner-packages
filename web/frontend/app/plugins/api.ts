import { createApiClient } from '~/lib/api'

export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()
  const baseURL = import.meta.server ? config.apiBaseInternal : config.public.apiBase
  return { provide: { api: createApiClient($fetch, baseURL) } }
})
