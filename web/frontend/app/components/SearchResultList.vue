<script setup lang="ts">
import type { PackageSummary } from '~/types/api'

defineProps<{ items: PackageSummary[]; active: number }>()
const emit = defineEmits<{ choose: [pkg: PackageSummary] }>()
</script>

<template>
  <ul role="listbox" class="divide-y divide-slate-100">
    <li v-for="(pkg, index) in items" :key="pkg.id">
      <button
        type="button"
        role="option"
        :aria-selected="active === index"
        class="grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-3 py-3 text-left hover:bg-slate-50"
        :class="active === index ? 'bg-slate-100' : ''"
        @mousedown.prevent="emit('choose', pkg)"
      >
        <PackageIcon :name="pkg.name" compact />
        <span class="min-w-0">
          <span class="flex items-center gap-2"><strong class="truncate">{{ pkg.name }}</strong><PackageBadge :value="pkg.latest_channel" /></span>
          <span class="mt-0.5 block truncate font-mono text-xs text-slate-500">{{ pkg.id }} · {{ pkg.publisher.name }}</span>
          <span class="mt-1 block truncate text-xs text-slate-500">{{ pkg.description }}</span>
        </span>
        <span class="text-right"><code class="text-xs font-semibold">{{ pkg.latest_version }}</code><span class="mt-1 block text-[11px] text-slate-500">{{ pkg.classification === 'first-party' ? 'First Party' : 'Community' }}</span></span>
      </button>
    </li>
  </ul>
</template>
