<script setup lang="ts">
import type { PackageSummary } from '~/types/api'
defineProps<{ compact?: boolean }>()
const router = useRouter()
const { $api } = useNuxtApp()
const query = ref('')
const results = ref<PackageSummary[]>([])
const open = ref(false)
const active = ref(-1)
const input = ref<HTMLInputElement>()
let timer: ReturnType<typeof setTimeout> | undefined

watch(query, (value) => {
  clearTimeout(timer)
  active.value = -1
  if (value.trim().length < 2) { results.value = []; open.value = false; return }
  timer = setTimeout(async () => {
    try { results.value = (await $api.search(value.trim())).items; open.value = true }
    catch { results.value = []; open.value = false }
  }, 220)
})

function choose(pkg: PackageSummary) { open.value = false; query.value = ''; router.push(`/packages/${pkg.id}`) }
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { open.value = false; input.value?.blur() }
  else if (event.key === 'ArrowDown') { event.preventDefault(); active.value = Math.min(active.value + 1, results.value.length - 1) }
  else if (event.key === 'ArrowUp') { event.preventDefault(); active.value = Math.max(active.value - 1, 0) }
  else if (event.key === 'Enter' && active.value >= 0) { event.preventDefault(); choose(results.value[active.value]!) }
  else if (event.key === 'Enter' && query.value.trim()) { router.push({ path: '/packages', query: { q: query.value.trim() } }); open.value = false }
}
function shortcut(event: KeyboardEvent) {
  const target = event.target as HTMLElement
  if (event.key === '/' && !['INPUT', 'TEXTAREA'].includes(target.tagName)) { event.preventDefault(); input.value?.focus() }
}
onMounted(() => document.addEventListener('keydown', shortcut))
onBeforeUnmount(() => { document.removeEventListener('keydown', shortcut); clearTimeout(timer) })
</script>
<template>
  <div class="relative" role="search">
    <label :class="compact ? 'sr-only' : 'mb-2 block text-sm font-semibold'" for="global-package-search">Search packages</label>
    <div class="relative"><span class="pointer-events-none absolute inset-y-0 left-3 grid place-items-center text-slate-400">⌕</span><input id="global-package-search" ref="input" v-model="query" type="search" autocomplete="off" placeholder="Search packages..." class="w-full rounded-xl border border-slate-300 bg-white py-3 pl-10 pr-10 text-slate-950 shadow-sm placeholder:text-slate-400" :aria-expanded="open" aria-controls="search-suggestions" @focus="open = results.length > 0" @keydown="onKeydown"><kbd class="absolute right-3 top-1/2 -translate-y-1/2 rounded border border-slate-300 px-1.5 text-xs text-slate-500">/</kbd></div>
    <ul v-if="open" id="search-suggestions" class="absolute z-50 mt-2 max-h-80 w-full overflow-auto rounded-xl border border-slate-200 bg-white p-2 text-slate-950 shadow-xl" role="listbox">
      <li v-for="(pkg, index) in results" :key="pkg.id"><button type="button" class="flex w-full items-center gap-3 rounded-lg p-3 text-left hover:bg-slate-50" :class="active === index ? 'bg-slate-100' : ''" role="option" :aria-selected="active === index" @mousedown.prevent="choose(pkg)"><PackageIcon :name="pkg.name" /><span><strong class="block">{{ pkg.name }}</strong><span class="text-sm text-slate-500">{{ pkg.publisher.name }} · {{ pkg.latest_version }}</span></span></button></li>
      <li v-if="!results.length" class="p-3 text-sm text-slate-500">No packages found.</li>
    </ul>
  </div>
</template>
