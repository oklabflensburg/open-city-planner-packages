<script setup lang="ts">
import type { PackageFilters } from '~/types/api'
const route = useRoute()
const router = useRouter()
const { $api } = useNuxtApp()
const filters = ref<PackageFilters>({ q: String(route.query.q || ''), sort: 'relevance', limit: 12, offset: 0 })
const filterKey = computed(() => JSON.stringify(filters.value))
const { data, status } = await useAsyncData('package-list', () => $api.packages(filters.value), { watch: [filterKey] })
const { data: publishers } = await useAsyncData('publisher-options', () => $api.publishers())
watch(filters, value => router.replace({ query: value.q ? { q: value.q } : {} }), { deep: true })
usePageSeo('Packages · Open City Planner', 'Search and filter reviewed Open City Planner modules.', '/packages')
</script>
<template>
  <div class="container-shell py-10"><header><p class="eyebrow">Registry v1</p><h1 class="page-title mt-2">Packages</h1><p class="mt-3 text-slate-600">Explore all available modules using verified Registry metadata.</p></header><div class="mt-8 grid gap-3 lg:grid-cols-[1fr_auto]"><label class="sr-only" for="package-query">Search packages</label><input id="package-query" v-model="filters.q" class="rounded-xl border border-slate-300 bg-white px-4 py-3" placeholder="Search packages..."><label class="flex items-center gap-2 text-sm font-semibold">Sort<select v-model="filters.sort" class="rounded-xl border border-slate-300 bg-white px-4 py-3"><option value="relevance">Relevance</option><option value="name">Name</option><option value="id">Package ID</option><option value="version">Latest version</option></select></label></div><div class="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]"><section aria-live="polite"><p class="mb-4 text-sm text-slate-500">{{ data?.total || 0 }} packages found</p><div v-if="status === 'pending'" class="surface-card p-8 text-center">Loading packages…</div><EmptyState v-else-if="!data?.items.length" title="No packages found" description="Try a broader search or clear the filters." /><div v-else class="grid gap-4"><PackageCard v-for="pkg in data.items" :key="pkg.id" :pkg="pkg" /></div><Pagination v-if="data" :total="data.total" :limit="data.limit" :offset="data.offset" @change="filters.offset = $event" /></section><FilterPanel v-model="filters" :publishers="publishers || []" class="order-first h-fit lg:order-last" /></div></div>
</template>
