<script setup lang="ts">
import { apiErrorStatus, safeUrl } from '~/lib/modulePresentation'
definePageMeta({ key: (route) => route.path })
const route = useRoute(),
  id = String(route.params.publisherId)
const { $api } = useNuxtApp()
const offset = ref(0)
const { data: publisher, error } = await useAsyncData(
  `publisher-${id}`,
  () => $api.publisher(id, offset.value),
  {
    watch: [offset],
    getCachedData: (key, app) =>
      app.isHydrating ? app.payload.data[key] : undefined,
  },
)
if (error.value || !publisher.value)
  throw createError({
    statusCode: apiErrorStatus(error.value),
    statusMessage: 'Publisher nicht verfügbar',
  })
const { data: registryModules, error: modulesError } = await useAsyncData(
  'hub-modules',
  () => $api.allModules(),
  {
    getCachedData: (key, app) =>
      app.isHydrating ? app.payload.data[key] : undefined,
  },
)
const publishedModules = computed(() =>
  modulesError.value
    ? []
    : registryModules.value?.filter((module) => module.publisher.id === id) ||
      [],
)
const versionCount = computed(() =>
  modulesError.value || !registryModules.value
    ? null
    : publishedModules.value.reduce(
        (sum, module) => sum + module.version_count,
        0,
      ),
)
const classifications = computed(() => [
  ...new Set(publishedModules.value.map((module) => module.classification)),
])
usePageSeo(
  `${publisher.value.name} – Open City Planner Package Hub`,
  `Veröffentlichte Module von ${publisher.value.name}.`,
  `/publishers/${id}`,
)
</script>
<template>
  <div>
    <HubHero />
    <section v-if="publisher" class="container-shell py-8">
      <nav class="breadcrumb">
        <NuxtLink to="/publishers">Publisher</NuxtLink><span>›</span>{{ id }}
      </nav>
      <h2 class="page-title">{{ publisher.name }}</h2>
      <p>
        {{ publisher.id }} · {{ publisher.module_count }} Module ·
        {{ versionCount ?? 'Nicht verfügbar' }} Versionen
      </p>
      <div class="my-4 flex flex-wrap gap-2">
        <span
          v-for="classification in classifications"
          :key="classification"
          class="channel-badge"
          :class="{ stable: classification === 'first-party' }"
          >{{
            classification === 'first-party'
              ? 'Offizielle Module'
              : 'Geprüfte Community-Module'
          }}</span
        >
      </div>
      <details v-if="publishedModules.length" class="my-4">
        <summary>Source-Repositories</summary>
        <ul>
          <li v-for="module in publishedModules" :key="module.id">
            <a
              v-if="safeUrl(module.source_repository)"
              :href="safeUrl(module.source_repository)"
              class="text-link"
              >{{ module.id }} ↗</a
            >
          </li>
        </ul>
      </details>
      <p v-if="error" role="alert">Module derzeit nicht verfügbar.</p>
      <template v-else
        ><PackageListItem
          v-for="pkg in publisher.modules.items"
          :key="pkg.id"
          :pkg="pkg" /><Pagination
          :total="publisher.modules.total"
          :limit="publisher.modules.limit"
          :offset="publisher.modules.offset"
          @change="offset = $event"
      /></template>
    </section>
  </div>
</template>
