<script setup lang="ts">
import type { PackageSummary } from '~/types/api'

const router = useRouter()
const { $api } = useNuxtApp()
const open = ref(false)
const query = ref('')
const packages = ref<PackageSummary[]>([])
const active = ref(0)
const input = ref<HTMLInputElement>()
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined
let requestId = 0
const baseCommands = [
  { label: 'Search packages', hint: 'Registry browser', to: '/packages' },
  { label: 'Open packages', hint: 'All modules', to: '/packages' },
  { label: 'Open publishers', hint: 'Package organizations', to: '/publishers' },
  { label: 'Open docs', hint: 'Registry and publishing', to: '/docs' },
  { label: 'Open GitHub', hint: 'Source repository', to: 'https://github.com/oklabflensburg/open-city-planner-packages' },
]
const commands = computed(() => {
  const needle = query.value.trim().toLowerCase()
  const navigation = baseCommands.filter(item => !needle || `${item.label} ${item.hint}`.toLowerCase().includes(needle))
  return [...packages.value.map(pkg => ({ label: pkg.name, hint: `${pkg.id} · ${pkg.latest_version}`, to: `/packages/${pkg.id}` })), ...navigation]
})
watch(query, value => {
  clearTimeout(timer); controller?.abort(); requestId += 1; packages.value = []; active.value = 0
  if (!value.trim()) return
  timer = setTimeout(async () => {
    const currentRequest = requestId
    controller = new AbortController()
    try {
      const response = await $api.search(value.trim(), 5, controller.signal)
      if (currentRequest === requestId) packages.value = response.items
    }
    catch { if (currentRequest === requestId) packages.value = [] }
  }, 160)
})
watch(open, async value => { if (value) { await nextTick(); input.value?.focus() } else { query.value = ''; packages.value = [] } })
function show() { open.value = true }
function hide() { open.value = false }
function choose(index = active.value) { const command = commands.value[index]; if (!command) return; hide(); if (command.to.startsWith('http')) window.location.assign(command.to); else router.push(command.to) }
function onGlobalKey(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); show() }
  else if (event.key === 'Escape' && open.value) hide()
}
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') hide()
  else if (event.key === 'ArrowDown' && commands.value.length) { event.preventDefault(); active.value = (active.value + 1) % commands.value.length }
  else if (event.key === 'ArrowUp' && commands.value.length) { event.preventDefault(); active.value = active.value <= 0 ? commands.value.length - 1 : active.value - 1 }
  else if (event.key === 'Enter') { event.preventDefault(); choose() }
}
onMounted(() => { document.addEventListener('keydown', onGlobalKey); window.addEventListener('ocp:open-command-palette', show) })
onBeforeUnmount(() => { document.removeEventListener('keydown', onGlobalKey); window.removeEventListener('ocp:open-command-palette', show); clearTimeout(timer); controller?.abort() })
</script>

<template><Teleport to="body"><div v-if="open" class="fixed inset-0 z-[100] bg-navy-950/70 p-3 backdrop-blur-sm sm:p-10" role="presentation" @mousedown.self="hide"><section role="dialog" aria-modal="true" aria-label="Open City Planner command palette" class="mx-auto mt-10 max-w-2xl overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl sm:mt-[10vh]"><div class="flex items-center gap-3 border-b border-slate-200 px-4"><span class="text-slate-400" aria-hidden="true">⌕</span><input ref="input" v-model="query" class="min-w-0 flex-1 py-4 outline-none" placeholder="Search packages or open a page…" aria-label="Command palette search" @keydown="onKeydown"><KeyboardHint :keys="['Esc']" /></div><ul class="max-h-[60vh] overflow-auto p-2" role="listbox"><li v-for="(command, index) in commands" :key="`${command.to}-${index}`"><button type="button" role="option" :aria-selected="active === index" class="flex w-full items-center justify-between rounded-lg px-3 py-3 text-left" :class="active === index ? 'bg-slate-100' : 'hover:bg-slate-50'" @click="choose(index)"><span class="font-semibold">{{ command.label }}</span><span class="text-xs text-slate-500">{{ command.hint }}</span></button></li></ul><footer class="flex items-center gap-4 border-t border-slate-100 px-4 py-2 text-xs text-slate-500"><span>↑↓ Navigate</span><span>↵ Open</span><span>Esc Close</span></footer></section></div></Teleport></template>
