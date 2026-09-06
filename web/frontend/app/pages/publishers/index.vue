<script setup lang="ts">
const { $api } = useNuxtApp()
const { data: publishers, error } = await useAsyncData('publishers', () =>
  $api.publishers(),
)
usePageSeo(
  'Publisher – Open City Planner Package Hub',
  'Organisationen und Teams mit veröffentlichten Open City Planner Modulen.',
  '/publishers',
)
</script>
<template>
  <div>
    <HubHero />
    <section class="container-shell py-8">
      <h2 class="page-title">Publisher</h2>
      <EmptyState
        v-if="error"
        title="Publisher derzeit nicht verfügbar"
        description="Die Registry API konnte nicht erreicht werden."
      />
      <p v-else-if="!publishers?.length" class="empty-text">
        Keine Publisher vorhanden.
      </p>
      <NuxtLink
        v-for="publisher in publishers"
        v-else
        :key="publisher.id"
        :to="`/publishers/${publisher.id}`"
        class="package-result"
        ><HubIcon name="users" />
        <div>
          <h3>{{ publisher.name }}</h3>
          <small>{{ publisher.id }}</small>
        </div>
        <span>{{ publisher.module_count }} Module →</span></NuxtLink
      >
    </section>
  </div>
</template>
