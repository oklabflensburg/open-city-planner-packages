<script setup lang="ts">defineProps<{ label: string; value: string }>()</script>
<template><span class="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs"><strong>{{ label }}</strong><span class="font-mono text-slate-600">{{ value }}</span></span></template>
