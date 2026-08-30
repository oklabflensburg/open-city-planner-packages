<script setup lang="ts">
const props = defineProps<{ value: string; label: string; truncate?: boolean }>()
const copied = ref(false)

async function copy() {
  await navigator.clipboard.writeText(props.value)
  copied.value = true
  window.setTimeout(() => { copied.value = false }, 1400)
}
</script>

<template>
  <span class="inline-flex min-w-0 items-center gap-2">
    <code class="min-w-0 text-xs text-slate-700" :class="truncate ? 'truncate' : 'break-all'">{{ value }}</code>
    <button type="button" class="shrink-0 rounded p-1 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-900" :aria-label="`Copy ${label}`" @click="copy">
      {{ copied ? 'Copied' : 'Copy' }}
    </button>
  </span>
</template>
