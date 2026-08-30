<script setup lang="ts">
const props = defineProps<{ total: number; limit: number; offset: number }>()
const emit = defineEmits<{ change: [offset: number] }>()
const page = computed(() => Math.floor(props.offset / props.limit) + 1)
const pages = computed(() => Math.max(1, Math.ceil(props.total / props.limit)))
</script>
<template><nav v-if="total > limit" class="mt-8 flex items-center justify-between" aria-label="Pagination"><button class="secondary-button" :disabled="offset === 0" @click="emit('change', Math.max(0, offset - limit))">Previous</button><span class="text-sm text-slate-600">Page {{ page }} of {{ pages }}</span><button class="secondary-button" :disabled="offset + limit >= total" @click="emit('change', offset + limit)">Next</button></nav></template>
