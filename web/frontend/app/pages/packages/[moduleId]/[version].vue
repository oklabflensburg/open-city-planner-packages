<script setup lang="ts">
import { apiErrorStatus } from '~/lib/modulePresentation'
definePageMeta({ key: (route) => route.path })
const route = useRoute()
const id = String(route.params.moduleId),
  versionId = String(route.params.version)
const { $api } = useNuxtApp()
const [
  { data: pkg, error: moduleError },
  { data: release, error: versionError },
] = await Promise.all([
  useAsyncData(`module-${id}`, () => $api.package(id), {
    getCachedData: (key, app) =>
      app.isHydrating ? app.payload.data[key] : undefined,
  }),
  useAsyncData(`version-${id}-${versionId}`, () => $api.version(id, versionId)),
])
if (moduleError.value || versionError.value || !pkg.value || !release.value)
  throw createError({
    statusCode: apiErrorStatus(moduleError.value || versionError.value),
    statusMessage: 'Version nicht verfügbar',
  })
usePageSeo(
  `${pkg.value.name} ${release.value.version} – Open City Planner Package Hub`,
  pkg.value.description || '',
  `/packages/${id}/${versionId}`,
)
</script>
<template>
  <div>
    <HubHero />
    <div v-if="pkg && release" class="container-shell detail-shell">
      <nav class="breadcrumb" aria-label="Breadcrumb">
        <NuxtLink to="/packages">Module</NuxtLink><span>›</span
        ><NuxtLink :to="`/packages/${id}`">{{ id }}</NuxtLink
        ><span>›</span>{{ release.version }}
      </nav>
      <div class="module-layout">
        <ModuleNavigation :active="id" />
        <article class="module-content">
          <h2 class="page-title">{{ pkg.name }} {{ release.version }}</h2>
          <p>{{ pkg.description }}</p>
          <div class="version-label">
            <template v-for="(target, channel) in pkg.channels" :key="channel"
              ><span
                v-if="target?.version === release.version"
                class="channel-badge"
                :class="channel"
                >{{ channel }}</span
              ></template
            >
          </div>
          <ProvenancePanel :pkg="pkg" :release="release" />
        </article>
        <aside class="metadata-rail">
          <DownloadCard :module-id="id" :release="release" />
          <section class="info-card">
            <h2>Lizenz</h2>
            <p>{{ pkg.license }}</p>
          </section>
        </aside>
      </div>
    </div>
  </div>
</template>
