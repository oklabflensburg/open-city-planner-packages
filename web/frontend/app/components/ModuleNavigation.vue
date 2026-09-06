<script setup lang="ts">
defineProps<{ active: string }>()
const { $api } = useNuxtApp()
const { data: modules, error } = await useAsyncData(
  'hub-modules',
  () => $api.allModules(),
  {
    getCachedData: (key, app) =>
      app.isHydrating ? app.payload.data[key] : undefined,
  },
)
const query = ref('')
const filtered = computed(
  () =>
    modules.value?.filter((m) =>
      `${m.id} ${m.name} ${m.description ?? ''}`
        .toLowerCase()
        .includes(query.value.toLowerCase()),
    ) || [],
)
</script>
<template>
  <aside class="module-navigation">
    <label class="module-search"
      ><HubIcon name="search" /><input
        v-model="query"
        type="search"
        placeholder="Module suchen ..."
        aria-label="Module suchen"
    /></label>
    <p v-if="error" class="empty-text" role="status">
      Modulliste nicht verfügbar.
    </p>
    <nav v-else aria-label="Modulnavigation">
      <NuxtLink
        v-for="module in filtered"
        :key="module.id"
        :to="`/packages/${module.id}`"
        :aria-current="module.id === active ? 'page' : undefined"
        :class="{ active: module.id === active }"
        ><PackageIcon :name="module.id" compact /><span
          ><strong>{{ module.id }}</strong
          ><small>{{
            module.description || 'Keine Beschreibung vorhanden.'
          }}</small></span
        ></NuxtLink
      >
      <p v-if="!filtered.length" class="empty-text">Keine Module gefunden.</p>
    </nav>
  </aside>
</template>
