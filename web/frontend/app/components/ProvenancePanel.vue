<script setup lang="ts">
import type { PackageDetail, PackageRelease } from '~/types/api'
import {
  safeUrl,
  publicationDate,
  installCommand,
} from '~/lib/modulePresentation'
defineProps<{ pkg: PackageDetail; release: PackageRelease }>()
</script>
<template>
  <section class="version-evidence">
    <h3>Version {{ release.version }}</h3>
    <dl>
      <div class="metadata-row">
        <dt>Veröffentlicht</dt>
        <dd>{{ publicationDate(release.published_at) }}</dd>
      </div>
      <div class="metadata-row">
        <dt>Source tag</dt>
        <dd>{{ release.source.tag || 'Nicht verfügbar' }}</dd>
      </div>
      <div class="metadata-row">
        <dt>Source commit</dt>
        <dd>
          <CopyValue
            :value="release.source.commit"
            label="Source commit"
            truncate
          />
        </dd>
      </div>
      <div class="metadata-row">
        <dt>SHA-256</dt>
        <dd>
          <CopyValue
            :value="release.artifact.sha256"
            label="SHA-256"
            truncate
          />
        </dd>
      </div>
      <div class="metadata-row">
        <dt>Artifact</dt>
        <dd>
          <a
            v-if="safeUrl(release.artifact.url)"
            :href="safeUrl(release.artifact.url)"
            download
            class="text-link"
            >{{ pkg.id }}-{{ release.version }}.ocp ↗</a
          >
        </dd>
      </div>
      <div class="metadata-row">
        <dt>Bundle-Format</dt>
        <dd>{{ release.bundle_format_version }}</dd>
      </div>
      <div class="metadata-row">
        <dt>Requirements</dt>
        <dd>
          Host {{ release.compatibility.host }}<br />SDK
          {{ release.compatibility.sdk }}
        </dd>
      </div>
      <div class="metadata-row">
        <dt>Abhängigkeiten</dt>
        <dd>
          {{
            Object.keys(release.dependencies).length
              ? release.dependencies
              : 'Keine Abhängigkeiten deklariert.'
          }}
        </dd>
      </div>
      <div
        v-for="[label, value] in [
          ['Builder', release.provenance.builder_version],
          ['Builder commit', release.provenance.builder_commit],
          ['Host commit', release.provenance.host_commit],
          [
            'Reproducibility',
            release.provenance.reproducible === null
              ? null
              : release.provenance.reproducible
                ? 'Reproduzierbar'
                : 'Nicht reproduzierbar',
          ],
          ['Host Contract', release.provenance.host_contract_status],
        ]"
        :key="String(label)"
        class="metadata-row"
      >
        <dt>{{ label }}</dt>
        <dd>{{ value ?? 'Nicht verfügbar' }}</dd>
      </div>
    </dl>
    <details v-if="release.provenance.environment">
      <summary>Provenance-Umgebung</summary>
      <pre>{{ JSON.stringify(release.provenance.environment, null, 2) }}</pre>
    </details>
    <CopyValue
      :value="installCommand(pkg.id, release)"
      label="Reproduzierbaren Installationsbefehl"
      block
    />
  </section>
</template>
