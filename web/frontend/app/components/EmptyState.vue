<script setup lang="ts">defineProps<{ title: string; description: string }>()</script>
<template><div class="surface-card p-10 text-center"><div class="mx-auto grid size-12 place-items-center rounded-full bg-slate-100 text-xl">⌕</div><h2 class="mt-4 text-lg font-bold">{{ title }}</h2><p class="mt-2 text-slate-600">{{ description }}</p></div></template>
