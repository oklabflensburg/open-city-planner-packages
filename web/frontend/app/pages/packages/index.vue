<script setup lang="ts">
import { packageFiltersFromQuery, packageFiltersToQuery } from '~/lib/packageFilters'
import type { PackageFilters } from '~/types/api'
const route = useRoute()
const router = useRouter()
const { $api } = useNuxtApp()

const filters = ref<PackageFilters>(packageFiltersFromQuery(route.query))
const searchQuery = ref(filters.value.q || '')
let queryTimer: ReturnType<typeof setTimeout> | undefined
watch(searchQuery, q => { clearTimeout(queryTimer); queryTimer = setTimeout(() => { filters.value = { ...filters.value, q, offset: 0 } }, 180) })

const filterKey = computed(() => JSON.stringify(filters.value))
const { data, status, error } = await useAsyncData('package-list', () => $api.packages(filters.value), { watch: [filterKey] })
const { data: publishers } = await useAsyncData('publisher-options', () => $api.publishers())

watch(filters, value => router.replace({ query: packageFiltersToQuery(value) }), { deep: true })
function clearFilters() { searchQuery.value = ''; filters.value = { q: '', sort: 'relevance', limit: 12, offset: 0 } }
onBeforeUnmount(() => clearTimeout(queryTimer))
usePageSeo('Packages · Open City Planner', 'Search and filter reviewed Open City Planner modules.', '/packages')
</script>

<template><div class="container-shell py-8"><header class="border-b border-slate-200 pb-7"><p class="eyebrow">Registry browser</p><h1 class="page-title mt-2">Packages</h1><p class="mt-2 text-slate-600">Search verified module metadata and share the exact result URL.</p><div class="mt-6 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]"><label class="relative"><span class="sr-only">Search packages</span><span class="pointer-events-none absolute inset-y-0 left-3 grid place-items-center text-slate-400">⌕</span><input id="package-query" v-model="searchQuery" class="w-full rounded-lg border border-slate-300 bg-white py-3 pl-10 pr-4" placeholder="Search packages…"></label><label class="flex items-center gap-2 text-sm font-semibold">Sort<select v-model="filters.sort" class="rounded-lg border border-slate-300 bg-white px-3 py-3"><option value="relevance">Relevance</option><option value="name">Name</option><option value="id">Package ID</option><option value="version">Latest version</option></select></label></div></header><div class="mt-6 grid gap-7 lg:grid-cols-[minmax(0,1fr)_260px]"><section aria-live="polite"><div class="mb-2 flex items-center justify-between"><p class="text-sm text-slate-500"><strong class="text-slate-800">{{ data?.total || 0 }}</strong> packages found</p><button v-if="Object.keys(route.query).length" type="button" class="text-sm font-semibold text-link-700" @click="clearFilters">Clear filters</button></div><div v-if="status === 'pending'" class="grid gap-2 py-3"><span v-for="index in 4" :key="index" class="h-28 animate-pulse rounded-lg bg-slate-100" /></div><EmptyState v-else-if="error" title="Package search is temporarily unavailable" description="Try again in a moment." /><EmptyState v-else-if="!data?.items.length" :title="`No packages found${searchQuery ? ` for “${searchQuery}”` : ''}`" description="Try a broader search or clear the filters." /><div v-else class="border-y border-slate-200"><PackageListItem v-for="pkg in data.items" :key="pkg.id" :pkg="pkg" show-compatibility /></div><Pagination v-if="data" :total="data.total" :limit="data.limit" :offset="data.offset" @change="filters.offset = $event" /></section><FilterPanel v-model="filters" :publishers="publishers || []" class="order-first h-fit lg:order-last" /></div></div></template>
