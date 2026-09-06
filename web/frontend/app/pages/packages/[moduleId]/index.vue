<script setup lang="ts">
import {
  apiErrorStatus,
  installCommand,
  safeUrl,
} from '~/lib/modulePresentation'
import type { PackageRelease } from '~/types/api'
definePageMeta({ key: (route) => route.path })
const route = useRoute()
const id = String(route.params.moduleId)
const { $api } = useNuxtApp()
const { data: pkg, error } = await useAsyncData(
  `module-${id}`,
  () => $api.package(id),
  {
    getCachedData: (key, app) =>
      app.isHydrating ? app.payload.data[key] : undefined,
  },
)
if (error.value || !pkg.value)
  throw createError({
    statusCode: apiErrorStatus(error.value),
    statusMessage:
      apiErrorStatus(error.value) === 404
        ? 'Modul nicht gefunden'
        : 'Registry API nicht verfügbar',
  })
// Resolve the immutable resource using this response's pointer. Never pick a version
// by array order or combine a later channels response with an earlier module response.
const { data: stable, error: stableError } = await useAsyncData(
  `stable-${id}-${pkg.value.channels.stable?.version || 'none'}`,
  async () => {
    const target = pkg.value!.channels.stable
    if (!target) return { release: null }
    const release = await $api.version(id, target.version)
    if (release.artifact.sha256 !== target.sha256)
      throw new Error('Channel digest mismatch')
    return { release }
  },
  {
    getCachedData: (key, app) =>
      app.isHydrating ? app.payload.data[key] : undefined,
  },
)
const tabs = [
  'Übersicht',
  'Versionen',
  'Installation',
  'Konfiguration',
  'Beispiele',
  'Abhängigkeiten',
  'Changelog',
]
const tab = ref('Übersicht')
const versionOffset = ref(0)
const {
  data: versions,
  status: versionsStatus,
  error: versionsError,
  execute: loadVersions,
} = await useAsyncData(
  `versions-${id}`,
  () => $api.versions(id, versionOffset.value),
  { immediate: false, watch: [versionOffset] },
)
watch(tab, (value) => {
  if (value === 'Versionen') loadVersions()
})
function tabKey(event: KeyboardEvent, index: number) {
  let next: number
  if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
  else if (event.key === 'ArrowLeft')
    next = (index + tabs.length - 1) % tabs.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = tabs.length - 1
  else return
  event.preventDefault()
  tab.value = tabs[next]!
  document.getElementById(`module-tab-${next}`)?.focus()
}
function selectTab(value: string) {
  tab.value = value
  nextTick(() =>
    document.getElementById(`module-tab-${tabs.indexOf(value)}`)?.focus(),
  )
}
const release = computed<PackageRelease | null>(() =>
  stableError.value ? null : stable.value?.release || null,
)
usePageSeo(
  `${pkg.value.name} – Open City Planner Package Hub`,
  pkg.value.description || '',
  `/packages/${id}`,
)
</script>
<template>
  <div>
    <HubHero />
    <div v-if="pkg" class="container-shell detail-shell">
      <nav class="breadcrumb" aria-label="Breadcrumb">
        <NuxtLink to="/packages">Module</NuxtLink
        ><span aria-hidden="true">›</span><span>{{ pkg.id }}</span>
      </nav>
      <div class="module-layout">
        <ModuleNavigation :active="id" />
        <article class="module-content">
          <header class="module-heading">
            <PackageIcon :name="pkg.id" />
            <div class="module-title">
              <div>
                <h2>{{ pkg.id }}</h2>
                <span
                  class="channel-badge stable"
                  v-if="pkg.classification === 'first-party'"
                  >Offizielles Modul</span
                ><span class="channel-badge" v-else>Community-Modul</span>
              </div>
              <p>{{ pkg.description || 'Keine Beschreibung vorhanden.' }}</p>
            </div>
            <div class="module-actions">
              <button
                type="button"
                class="primary-button"
                @click="selectTab('Installation')"
              >
                <HubIcon name="terminal" />Mit OCP installieren</button
              ><a
                v-if="safeUrl(pkg.source_repository)"
                :href="safeUrl(pkg.source_repository)"
                class="secondary-button"
                ><HubIcon name="github" />Quellcode anzeigen</a
              >
            </div>
            <dl class="module-meta">
              <div>
                <dt class="sr-only">Publisher</dt>
                <dd>
                  <HubIcon name="users" /><NuxtLink
                    :to="`/publishers/${pkg.publisher.id}`"
                    >{{ pkg.publisher.id }}</NuxtLink
                  >
                </dd>
              </div>
              <div>
                <dt>
                  <HubIcon name="download" /><span class="sr-only"
                    >Downloads</span
                  >
                </dt>
                <dd>Nicht verfügbar</dd>
              </div>
              <div>
                <dt>
                  <HubIcon name="star" /><span class="sr-only">Stars</span>
                </dt>
                <dd>Nicht verfügbar</dd>
              </div>
              <div>
                <dt><HubIcon name="clock" />Zuletzt aktualisiert:</dt>
                <dd>Nicht verfügbar</dd>
              </div>
            </dl>
          </header>
          <div class="module-tabs" role="tablist" aria-label="Moduldetails">
            <button
              v-for="(name, index) in tabs"
              :id="`module-tab-${index}`"
              :key="name"
              role="tab"
              type="button"
              :aria-selected="tab === name"
              :tabindex="tab === name ? 0 : -1"
              aria-controls="module-panel"
              @click="tab = name"
              @keydown="tabKey($event, index)"
            >
              {{ name }}
            </button>
          </div>
          <section
            id="module-panel"
            class="module-panel"
            role="tabpanel"
            :aria-labelledby="`module-tab-${tabs.indexOf(tab)}`"
            tabindex="0"
          >
            <template v-if="tab === 'Übersicht'"
              ><h3>Über dieses Modul</h3>
              <p>{{ pkg.description || 'Keine Beschreibung vorhanden.' }}</p>
              <div class="feature-empty">
                <HubIcon name="document" />
                <p>Keine strukturierten Feature-Angaben vorhanden.</p>
              </div>
              <h3 class="quickstart-heading">Schnellstart</h3>
              <p>Installiere das Modul mit dem OCP CLI:</p>
              <CopyValue
                :value="installCommand(id)"
                label="Installationsbefehl"
                block
              /><template v-if="release"
                ><p class="code-caption">Oder eine bestimmte Version:</p>
                <CopyValue
                  :value="`ocp module install-registry ${id} --version ${release.version}`"
                  label="Versionsbefehl"
                  block
              /></template>
              <p v-else class="empty-text">
                {{
                  stableError
                    ? 'Stable-Versionsdaten nicht verfügbar.'
                    : 'Keine Stable-Version veröffentlicht.'
                }}
              </p>
              <div class="requirements-box">
                <span aria-hidden="true">i</span>
                <div>
                  <strong>Voraussetzungen</strong>
                  <p>
                    {{
                      release
                        ? `Open City Planner: ${release.compatibility.host} · SDK: ${release.compatibility.sdk}`
                        : 'Nicht verfügbar'
                    }}
                  </p>
                </div>
              </div></template
            ><template v-else-if="tab === 'Versionen'"
              ><h3>Versionen</h3>
              <p v-if="versionsStatus === 'pending'" role="status">
                Versionen werden geladen …
              </p>
              <p v-else-if="versionsError" role="alert">
                Versionen derzeit nicht verfügbar.
                <button type="button" class="text-link" @click="loadVersions()">
                  Erneut versuchen
                </button>
              </p>
              <template v-else
                ><section
                  v-for="version in versions?.items"
                  :key="version.version"
                  class="version-entry"
                >
                  <div class="version-label">
                    <NuxtLink :to="`/packages/${id}/${version.version}`">{{
                      version.version
                    }}</NuxtLink
                    ><template
                      v-for="(target, channel) in pkg.channels"
                      :key="channel"
                      ><span
                        v-if="target?.version === version.version"
                        class="channel-badge"
                        :class="channel"
                        >{{ channel }}</span
                      ></template
                    >
                  </div>
                  <ProvenancePanel :pkg="pkg" :release="version" />
                </section>
                <Pagination
                  v-if="versions"
                  :total="versions.total"
                  :limit="versions.limit"
                  :offset="versions.offset"
                  @change="versionOffset = $event" /></template></template
            ><template v-else-if="tab === 'Installation'"
              ><h3>Installation</h3>
              <p>Installation aus dem Stable-Channel:</p>
              <CopyValue
                :value="installCommand(id)"
                label="Installationsbefehl"
                block
              /><template v-if="release"
                ><h3>Reproduzierbare Installation</h3>
                <p>Version {{ release.version }} mit festem SHA-256:</p>
                <CopyValue
                  :value="installCommand(id, release)"
                  label="Reproduzierbaren Installationsbefehl"
                  block
              /></template>
              <p v-else>
                Keine Stable-Versionsdaten für eine gepinnte Installation
                verfügbar.
              </p></template
            ><template v-else-if="tab === 'Abhängigkeiten'"
              ><h3>Abhängigkeiten</h3>
              <p v-if="!release">Stable-Versionsdaten nicht verfügbar.</p>
              <dl v-else-if="Object.keys(release.dependencies).length">
                <div
                  v-for="(constraint, dependency) in release.dependencies"
                  :key="dependency"
                  class="metadata-row"
                >
                  <dt>{{ dependency }}</dt>
                  <dd>{{ constraint }}</dd>
                </div>
              </dl>
              <p v-else>Keine Abhängigkeiten deklariert.</p></template
            ><template v-else
              ><h3>{{ tab }}</h3>
              <p>
                {{
                  tab === 'Konfiguration'
                    ? 'Keine Konfigurationsdokumentation hinterlegt.'
                    : tab === 'Beispiele'
                      ? 'Keine Beispiele hinterlegt.'
                      : 'Keine Changelog-Daten vorhanden.'
                }}
              </p>
              <a
                v-if="safeUrl(pkg.documentation_url)"
                :href="safeUrl(pkg.documentation_url)"
                class="text-link"
                >Dokumentation öffnen ↗</a
              ></template
            >
          </section>
        </article>
        <PackageMetadataRail
          :pkg="pkg"
          :release="release"
          @versions="selectTab('Versionen')"
        />
      </div>
    </div>
  </div>
</template>
