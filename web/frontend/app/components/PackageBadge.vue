<script setup lang="ts">
const props = defineProps<{ value: string }>()
const tone = computed(() => {
  if (props.value === 'beta') return 'bg-amber-100 text-amber-800'
  if (props.value === 'nightly') return 'bg-violet-100 text-violet-800'
  if (props.value === 'reviewed-community') return 'bg-violet-100 text-violet-800'
  return 'bg-brand-100 text-brand-700'
})
</script>
<template><span class="inline-flex rounded-full px-2.5 py-1 text-xs font-semibold capitalize" :class="tone">{{ value.replaceAll('-', ' ') }}</span></template>
