<script setup lang="ts">
import type { PackageDetail, PackageRelease } from '~/types/api'
import {
  publicationDate,
  repositoryLinks,
  safeUrl,
} from '~/lib/modulePresentation'
const props = defineProps<{
  pkg: PackageDetail
  release?: PackageRelease | null
}>()
const emit = defineEmits<{ versions: [] }>()
const repository = computed(() => repositoryLinks(props.pkg.source_repository))
const additional = computed(() =>
  Object.entries(props.pkg.channels).filter(
    ([channel]) => channel !== 'stable',
  ),
)
</script>
<template>
  <aside class="metadata-rail">
    <section class="info-card stable-card">
      <div class="card-heading">
        <h2>Stable Version</h2>
        <span v-if="pkg.channels.stable" class="channel-badge stable"
          >stable</span
        >
      </div>
      <template v-if="pkg.channels.stable"
        ><strong class="stable-number">{{
          pkg.channels.stable.version
        }}</strong>
        <p class="stable-status">✓ <span>Aktuell und empfohlen</span></p>
        <dl class="stable-facts">
          <div>
            <dt>Veröffentlicht</dt>
            <dd>{{ publicationDate(release?.published_at) }}</dd>
          </div>
          <div>
            <dt>Kompatibilität</dt>
            <dd>
              {{
                release
                  ? `OCP ${release.compatibility.host}`
                  : 'Nicht verfügbar'
              }}
            </dd>
          </div>
          <div>
            <dt>Download (.ocp)</dt>
            <dd>
              <a
                v-if="release && safeUrl(release.artifact.url)"
                :href="safeUrl(release.artifact.url)"
                download
                class="download-icon"
                :aria-label="`${pkg.id} ${release.version} herunterladen`"
                ><HubIcon name="download" /></a
              ><span v-else>Nicht verfügbar</span>
            </dd>
          </div>
          <div>
            <dt>SHA-256</dt>
            <dd>
              <CopyValue
                :value="pkg.channels.stable.sha256"
                label="SHA-256"
                truncate
              />
            </dd>
          </div></dl
      ></template>
      <p v-else class="empty-text">Keine Stable-Version veröffentlicht.</p>
      <button type="button" class="all-versions" @click="emit('versions')">
        Alle Versionen anzeigen →
      </button>
    </section>
    <section class="info-card channels-card">
      <h2>Weitere Channels</h2>
      <dl v-if="additional.length" class="other-channels">
        <div v-for="[channel, target] in additional" :key="channel">
          <dt>
            <span class="channel-badge" :class="channel">{{ channel }}</span>
          </dt>
          <dd>
            <NuxtLink :to="`/packages/${pkg.id}/${target.version}`">{{
              target.version
            }}</NuxtLink>
          </dd>
        </div>
      </dl>
      <p v-else class="empty-text">Keine weiteren Channels</p>
    </section>
    <section class="info-card repository-card">
      <h2>Repository</h2>
      <a
        v-if="repository.source"
        :href="repository.source"
        class="repository-name"
        ><HubIcon name="github" />{{ repository.label }}</a
      >
      <ul>
        <li v-if="repository.source">
          <HubIcon name="code" /><a :href="repository.source"
            >Quellcode <HubIcon name="external"
          /></a>
        </li>
        <li v-if="repository.issues">
          <HubIcon name="clock" /><a :href="repository.issues"
            >Issues <HubIcon name="external"
          /></a>
        </li>
        <li v-if="repository.releases">
          <HubIcon name="tag" /><a :href="repository.releases"
            >Releases <HubIcon name="external"
          /></a>
        </li>
        <li v-if="safeUrl(pkg.documentation_url)">
          <HubIcon name="document" /><a :href="safeUrl(pkg.documentation_url)"
            >Dokumentation <HubIcon name="external"
          /></a>
        </li>
      </ul>
      <p v-if="!safeUrl(pkg.documentation_url)" class="empty-text">
        Keine Dokumentation hinterlegt.
      </p>
    </section>
    <section class="info-card license-card">
      <h2>Lizenz</h2>
      <strong>{{ pkg.license }}</strong>
      <p>Lizenz laut Modul-Registry.</p>
    </section>
  </aside>
</template>
