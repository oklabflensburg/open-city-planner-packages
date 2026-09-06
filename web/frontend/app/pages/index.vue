<script setup lang="ts">
const { $api } = useNuxtApp()
const { data, error } = await useAsyncData('featured-modules', () =>
  $api.modules({ limit: 6 }),
)
usePageSeo(
  'Open City Planner Package Hub',
  'Module für offene Stadtplanung. Entdecke Module, Versionen und Publisher für den Open City Planner.',
  '/',
)
</script>
<template>
  <div>
    <HubHero />
    <section class="container-shell py-8">
      <div class="flex items-center justify-between">
        <h2 class="page-title">Module entdecken</h2>
        <NuxtLink to="/packages" class="text-link">Alle Module →</NuxtLink>
      </div>
      <EmptyState
        v-if="error"
        title="Registry API nicht verfügbar"
        description="Bitte versuche es später erneut."
      /><EmptyState
        v-else-if="!data?.items.length"
        title="Keine Module veröffentlicht"
        description="Hier erscheinen veröffentlichte Module."
      /><PackageListItem
        v-for="pkg in data?.items"
        v-else
        :key="pkg.id"
        :pkg="pkg"
      />
    </section>
  </div>
</template>
