<script setup lang="ts">
import type { PackageSummary } from '~/types/api'

withDefaults(defineProps<{ compact?: boolean; prominent?: boolean }>(), { compact: false, prominent: false })
const router = useRouter()
const { $api } = useNuxtApp()
const inputId = `package-search-${useId()}`
const query = ref('')
const results = ref<PackageSummary[]>([])
const panelOpen = ref(false)
const active = ref(-1)
const pending = ref(false)
const failed = ref(false)
const input = ref<HTMLInputElement>()
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined
let requestId = 0

watch(query, (value) => {
  clearTimeout(timer)
  controller?.abort()
  requestId += 1
  active.value = -1
  failed.value = false
  const trimmed = value.trim()
  if (!trimmed) { results.value = []; pending.value = false; return }
  panelOpen.value = true
  pending.value = true
  timer = setTimeout(async () => {
    const currentRequest = requestId
    controller = new AbortController()
    try {
      const response = await $api.search(trimmed, 8, controller.signal)
      if (currentRequest === requestId) results.value = response.items
    }
    catch (error) {
      if (currentRequest === requestId) {
        if ((error as Error).name !== 'AbortError') failed.value = true
        results.value = []
      }
    }
    finally { if (currentRequest === requestId) pending.value = false }
  }, 160)
})

function choose(pkg: PackageSummary) { panelOpen.value = false; query.value = ''; router.push(`/packages/${pkg.id}`) }
function submitSearch() {
  if (!query.value.trim()) return
  panelOpen.value = false
  router.push({ path: '/packages', query: { q: query.value.trim() } })
}
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { panelOpen.value = false; input.value?.blur() }
  else if (event.key === 'ArrowDown' && results.value.length) { event.preventDefault(); active.value = (active.value + 1) % results.value.length }
  else if (event.key === 'ArrowUp' && results.value.length) { event.preventDefault(); active.value = active.value <= 0 ? results.value.length - 1 : active.value - 1 }
  else if (event.key === 'Enter' && active.value >= 0) { event.preventDefault(); choose(results.value[active.value]!) }
  else if (event.key === 'Enter') { event.preventDefault(); submitSearch() }
}
function shortcut(event: KeyboardEvent) {
  const target = event.target as HTMLElement
  if (event.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) { event.preventDefault(); input.value?.focus(); panelOpen.value = true }
}
onMounted(() => document.addEventListener('keydown', shortcut))
onBeforeUnmount(() => { document.removeEventListener('keydown', shortcut); clearTimeout(timer); controller?.abort() })
</script>

<template>
  <div class="relative" role="search">
    <label :class="compact ? 'sr-only' : 'mb-2 block text-sm font-semibold'" :for="inputId">Search packages</label>
    <div class="relative">
      <span class="pointer-events-none absolute inset-y-0 left-3 grid place-items-center text-slate-400" aria-hidden="true">⌕</span>
      <input :id="inputId" ref="input" v-model="query" type="search" autocomplete="off" placeholder="Search packages…" class="w-full border border-slate-300 bg-white pl-10 pr-14 text-slate-950 shadow-sm placeholder:text-slate-400" :class="prominent ? 'rounded-xl py-4 text-base' : 'rounded-lg py-2.5 text-sm'" :aria-expanded="panelOpen" :aria-controls="`${inputId}-results`" aria-autocomplete="list" @focus="panelOpen = true" @keydown="onKeydown">
      <span class="absolute right-3 top-1/2 -translate-y-1/2"><KeyboardHint :keys="['/']" /></span>
    </div>
    <div v-if="panelOpen" :id="`${inputId}-results`" class="absolute z-50 mt-2 max-h-[min(31rem,70vh)] w-full overflow-auto rounded-xl border border-slate-200 bg-white p-2 text-slate-950 shadow-2xl">
      <div v-if="!query.trim()" class="p-2">
        <p class="muted-label px-2">Quick navigation</p>
        <div class="mt-2 grid"><NuxtLink to="/packages" class="rounded-lg px-3 py-2.5 text-sm font-semibold hover:bg-slate-50">Browse all packages <span class="float-right text-slate-400">→</span></NuxtLink><NuxtLink to="/publishers" class="rounded-lg px-3 py-2.5 text-sm font-semibold hover:bg-slate-50">Open publishers <span class="float-right text-slate-400">→</span></NuxtLink><NuxtLink to="/docs" class="rounded-lg px-3 py-2.5 text-sm font-semibold hover:bg-slate-50">Read documentation <span class="float-right text-slate-400">→</span></NuxtLink></div>
        <p class="mt-3 border-t border-slate-100 px-2 pt-3 text-xs text-slate-500">Type to search Registry v1 metadata. Use ↑ ↓ and Enter to navigate.</p>
      </div>
      <div v-else-if="pending" class="grid gap-2 p-2" aria-live="polite"><span v-for="index in 3" :key="index" class="h-14 animate-pulse rounded-lg bg-slate-100" /></div>
      <div v-else-if="failed" class="p-4 text-sm text-slate-600"><strong class="block text-slate-900">Package search is temporarily unavailable.</strong> Try again in a moment.</div>
      <template v-else-if="results.length"><SearchResultList :items="results" :active="active" @choose="choose" /><button type="button" class="mt-2 w-full border-t border-slate-100 px-3 py-3 text-left text-sm font-semibold text-link-700" @click="submitSearch">View all results for “{{ query }}” →</button></template>
      <div v-else class="p-4 text-sm text-slate-600">No packages found for “{{ query }}”.</div>
    </div>
  </div>
</template>
