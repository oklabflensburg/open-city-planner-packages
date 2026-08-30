<script setup lang="ts">
const props = defineProps<{ name: string }>()
const initials = computed(() => props.name.split(/\s+/).map(word => word[0]).join('').slice(0, 2).toUpperCase())
</script>
<template><span class="grid size-12 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 font-bold text-white shadow-sm" aria-hidden="true">{{ initials }}</span></template>
