<script setup lang="ts">
import type { PackageRelease } from '~/types/api'
const props = defineProps<{ moduleId: string; release: PackageRelease; flat?: boolean }>()
const filename = computed(() => `${props.moduleId}-${props.release.version}.ocp`)
</script>
<template><aside :class="flat ? '' : 'surface-card p-5'"><a :href="release.artifact.url" class="primary-button w-full" download>↓ Download {{ release.version }}</a><p class="mt-2 truncate text-center font-mono text-[11px] text-slate-500">{{ filename }}</p><div class="mt-3 border-t border-slate-100 pt-3"><p class="muted-label">SHA-256</p><CopyValue class="mt-1" :value="release.artifact.sha256" label="SHA-256" truncate /></div></aside></template>
