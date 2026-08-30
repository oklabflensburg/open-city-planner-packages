<script setup lang="ts">
defineProps<{ keys: string[] }>()
</script>

<template>
  <span class="inline-flex items-center gap-1" aria-hidden="true">
    <kbd v-for="key in keys" :key="key" class="min-w-5 rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 text-center font-sans text-[11px] font-medium text-slate-500 shadow-sm">{{ key }}</kbd>
  </span>
</template>
