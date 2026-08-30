<script setup lang="ts">
import type { Classification, Publisher } from '~/types/api'
defineProps<{ publisher: Publisher; classification?: Classification }>()
</script>
<template><span class="inline-flex flex-wrap items-center gap-2 text-sm text-slate-600"><span class="font-medium">{{ publisher.name }}</span><span v-if="classification" class="rounded-full bg-slate-100 px-2 py-0.5 text-xs">{{ classification === 'first-party' ? 'First Party' : 'Reviewed Community' }}</span></span></template>
