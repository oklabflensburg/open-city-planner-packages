<script setup lang="ts">
const props = defineProps<{ name: string; compact?: boolean }>()
const initials = computed(() => props.name.split(/\s+/).map(word => word[0]).join('').slice(0, 2).toUpperCase())
</script>
<template><span class="grid shrink-0 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 font-bold text-white shadow-sm" :class="compact ? 'size-10 text-xs' : 'size-12'" aria-hidden="true">{{ initials }}</span></template>
