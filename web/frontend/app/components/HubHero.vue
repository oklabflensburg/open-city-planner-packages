<script setup lang="ts">
const { $api } = useNuxtApp()
const { data: modules, error } = await useAsyncData(
  'hub-modules',
  () => $api.allModules(),
  {
    getCachedData: (key, app) =>
      app.isHydrating ? app.payload.data[key] : undefined,
  },
)
// These SPDX identifiers are unambiguously open-source licenses. Unknown expressions
// cannot establish a percentage, and are not silently treated as proprietary or open.
const openLicenses = new Set([
  'AGPL-3.0-only',
  'AGPL-3.0-or-later',
  'GPL-3.0-only',
  'GPL-3.0-or-later',
  'MIT',
  'Apache-2.0',
  'BSD-2-Clause',
  'BSD-3-Clause',
  'MPL-2.0',
])
const stats = computed(() => {
  const items = error.value ? undefined : modules.value
  return [
    { icon: 'cube', label: 'Module', value: items?.length },
    {
      icon: 'tag',
      label: 'Versionen',
      value: items?.reduce((sum, m) => sum + m.version_count, 0),
    },
    {
      icon: 'users',
      label: 'Publisher',
      value: items ? new Set(items.map((m) => m.publisher.id)).size : undefined,
    },
    {
      icon: 'lock',
      label: 'Open Source',
      value:
        items?.length && items.every((m) => openLicenses.has(m.license))
          ? `${Math.round((100 * items.filter((m) => openLicenses.has(m.license)).length) / items.length)}%`
          : undefined,
    },
  ]
})
</script>
<template>
  <section class="hub-hero" aria-labelledby="hub-hero-title">
    <div class="hero-inner">
      <div class="hero-copy">
        <h1 id="hub-hero-title">
          Module für offene<br /><span>Stadtplanung.</span>
        </h1>
        <p>
          Erweitere den Open City Planner mit Community- und<br
            class="desktop-break"
          />
          offiziellen Modulen. Analysieren, visualisieren, planen –<br
            class="desktop-break"
          />
          auf Basis offener Daten.
        </p>
        <div class="hero-actions">
          <NuxtLink to="/packages" class="primary-button"
            >Module entdecken <HubIcon name="arrow" /></NuxtLink
          ><NuxtLink to="/docs" class="hero-docs">Dokumentation</NuxtLink>
        </div>
        <dl class="hero-stats">
          <div v-for="stat in stats" :key="stat.label">
            <HubIcon :name="stat.icon" /><span
              ><dd :class="{ unavailable: stat.value === undefined }">
                {{ stat.value ?? 'Nicht verfügbar' }}
              </dd>
              <dt>{{ stat.label }}</dt></span
            >
          </div>
        </dl>
      </div>
      <img
        class="hero-art"
        src="/gis-layers.svg"
        alt="Fünf übereinanderliegende GIS-Kartenschichten: OpenStreetMap, Statistikdaten, Planungsgebiete, Umweltdaten und eigene Daten"
        width="720"
        height="310"
      />
    </div>
  </section>
</template>
