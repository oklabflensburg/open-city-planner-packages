<script setup lang="ts">
import type { PackageDetail, PackageRelease } from '~/types/api'

defineProps<{ pkg: PackageDetail; release: PackageRelease }>()
</script>

<template>
  <aside class="h-fit border-t border-slate-200 pt-5 lg:border-l lg:border-t-0 lg:pl-7 lg:pt-0">
    <div class="flex items-center justify-between"><h2 class="font-bold">Release metadata</h2><PackageBadge :value="release.channel" /></div>
    <dl class="mt-4 text-sm">
      <div class="metadata-row"><dt class="text-slate-500">Latest</dt><dd class="font-mono font-semibold">{{ release.version }}</dd></div>
      <div class="metadata-row"><dt class="text-slate-500">Package ID</dt><dd><CopyValue :value="pkg.id" label="package ID" truncate /></dd></div>
      <div class="metadata-row"><dt class="text-slate-500">Host</dt><dd class="font-mono text-xs">{{ release.requires.host }}</dd></div>
      <div class="metadata-row"><dt class="text-slate-500">SDK</dt><dd class="font-mono text-xs">{{ release.requires.sdk }}</dd></div>
      <div class="metadata-row"><dt class="text-slate-500">License</dt><dd>{{ pkg.license }}</dd></div>
      <div class="metadata-row"><dt class="text-slate-500">Publisher</dt><dd><NuxtLink :to="`/publishers/${pkg.publisher.id}`" class="text-link">{{ pkg.publisher.id }}</NuxtLink></dd></div>
      <div class="metadata-row"><dt class="text-slate-500">Bundle</dt><dd class="font-mono">v{{ release.bundle_format_version }}</dd></div>
    </dl>
    <div class="mt-5"><DownloadCard :module-id="pkg.id" :release="release" flat /></div>
  </aside>
</template>
