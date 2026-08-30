<script setup lang="ts">
import type { PackageRelease } from '~/types/api'

const props = defineProps<{ moduleId: string; versions: PackageRelease[]; selected: string }>()
const router = useRouter()

function navigate(event: Event) {
  const version = (event.target as HTMLSelectElement).value
  router.push(`/packages/${props.moduleId}/${version}`)
}
</script>

<template>
  <label class="flex items-center gap-2 text-sm font-semibold text-slate-700">
    Version
    <select :value="selected" class="rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm" @change="navigate">
      <option v-for="release in versions" :key="release.version" :value="release.version">{{ release.version }}</option>
    </select>
  </label>
</template>
