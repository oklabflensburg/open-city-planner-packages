<script setup lang="ts">
import type { PackageSummary } from '~/types/api'
defineProps<{ pkg: PackageSummary; compact?: boolean }>()
</script>
<template>
  <NuxtLink :to="`/packages/${pkg.id}`" class="surface-card group flex h-full gap-4 p-5 transition hover:-translate-y-0.5 hover:border-brand-500 hover:shadow-lg">
    <PackageIcon :name="pkg.name" />
    <div class="min-w-0 flex-1"><div class="flex flex-wrap items-start justify-between gap-2"><div><h3 class="font-bold text-slate-950 group-hover:text-brand-700">{{ pkg.name }}</h3><PublisherBadge :publisher="pkg.publisher" :classification="pkg.classification" /></div><PackageBadge :value="pkg.latest_channel" /></div><p v-if="!compact" class="mt-3 line-clamp-2 text-sm leading-6 text-slate-600">{{ pkg.description }}</p><div class="mt-4 flex flex-wrap gap-2"><VersionBadge :version="pkg.latest_version" /><CompatibilityBadge label="Host" :value="pkg.compatibility.host" /><CompatibilityBadge label="SDK" :value="pkg.compatibility.sdk" /></div></div>
  </NuxtLink>
</template>
