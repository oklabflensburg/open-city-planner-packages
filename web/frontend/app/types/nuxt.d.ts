import type { ApiClient } from '~/lib/api'

declare module '#app' {
  interface NuxtApp { $api: ApiClient }
}

declare module 'vue' {
  interface ComponentCustomProperties { $api: ApiClient }
}

export {}
