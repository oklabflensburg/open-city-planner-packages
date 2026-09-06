<script setup lang="ts">
import type { PackageSummary } from '~/types/api'
defineProps<{ pkg: PackageSummary; showCompatibility?: boolean }>()
</script>
<template>
  <NuxtLink :to="`/packages/${pkg.id}`" class="package-result"
    ><PackageIcon :name="pkg.id" compact />
    <div>
      <h3>{{ pkg.name }}</h3>
      <small>{{ pkg.id }}</small>
      <p>{{ pkg.description }}</p>
      <small
        >{{ pkg.publisher.name }} ·
        {{
          pkg.classification === 'first-party'
            ? 'Offizielles Modul'
            : 'Community-Modul'
        }}</small
      >
    </div>
    <div class="result-version">
      <strong>{{
        pkg.channels.stable?.version || 'Keine Stable-Version'
      }}</strong
      ><small>Stable Version</small><span>Modul anzeigen →</span>
    </div></NuxtLink
  >
</template>
