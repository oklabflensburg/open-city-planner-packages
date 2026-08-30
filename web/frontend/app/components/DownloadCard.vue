<script setup lang="ts">
import type { PackageRelease } from '~/types/api'
const props = defineProps<{ moduleId: string; release: PackageRelease }>()
const filename = computed(() => `${props.moduleId}-${props.release.version}.ocp`)
</script>
<template><aside class="surface-card p-5"><a :href="release.artifact.url" class="primary-button w-full" download>↓ Download {{ release.version }}</a><p class="mt-3 text-center text-xs text-slate-500">{{ filename }}</p><div class="mt-4 border-t border-slate-100 pt-4"><p class="muted-label">SHA-256</p><code class="mt-1 block break-all text-xs text-slate-600">{{ release.artifact.sha256 }}</code></div></aside></template>
