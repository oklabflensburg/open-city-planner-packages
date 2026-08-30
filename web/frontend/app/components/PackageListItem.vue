<script setup lang="ts">
import type { PackageSummary } from '~/types/api'

defineProps<{ pkg: PackageSummary; showCompatibility?: boolean }>()
</script>

<template>
  <NuxtLink
    :to="`/packages/${pkg.id}`"
    class="group grid gap-4 border-b border-slate-200 px-1 py-5 transition last:border-0 hover:bg-white sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:px-3"
  >
    <PackageIcon :name="pkg.name" compact />
    <div class="min-w-0">
      <div class="flex flex-wrap items-center gap-2">
        <h3 class="font-bold text-slate-950 group-hover:text-link-700">{{ pkg.name }}</h3>
        <PackageBadge :value="pkg.latest_channel" />
      </div>
      <p class="mt-0.5 font-mono text-xs text-slate-500">{{ pkg.id }}</p>
      <p class="mt-2 line-clamp-2 text-sm leading-6 text-slate-600">{{ pkg.description }}</p>
      <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        <span>{{ pkg.publisher.name }}</span>
        <span aria-hidden="true">·</span>
        <span>{{ pkg.classification === 'first-party' ? 'First Party' : 'Reviewed Community' }}</span>
        <template v-if="showCompatibility">
          <span aria-hidden="true">·</span>
          <span>Host <code>{{ pkg.compatibility.host }}</code></span>
          <span>SDK <code>{{ pkg.compatibility.sdk }}</code></span>
        </template>
      </div>
    </div>
    <div class="flex items-center justify-between gap-4 sm:block sm:min-w-28 sm:text-right">
      <code class="text-sm font-semibold text-slate-800">{{ pkg.latest_version }}</code>
      <p class="mt-1 text-xs text-slate-500">Latest release</p>
      <span class="mt-3 hidden text-sm font-semibold text-link-700 sm:block">View package →</span>
    </div>
  </NuxtLink>
</template>
