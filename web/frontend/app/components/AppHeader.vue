<script setup lang="ts">
const menuOpen = ref(false)
const route = useRoute()
watch(
  () => route.fullPath,
  () => {
    menuOpen.value = false
  },
)
const links = [
  { label: 'Module', to: '/packages' },
  { label: 'Publisher', to: '/publishers' },
  { label: 'Dokumentation', to: '/docs' },
  { label: 'Community', to: '/about' },
]
</script>
<template>
  <header class="hub-header">
    <a href="#main-content" class="sr-only focus:not-sr-only">Zum Inhalt</a>
    <div class="header-inner">
      <NuxtLink
        to="/"
        class="hub-brand"
        aria-label="Open City Planner Package Hub Startseite"
        ><img src="/logo.svg" width="36" height="43" alt="" /><span
          ><strong>Open City Planner</strong><span>Package Hub</span></span
        ></NuxtLink
      >
      <nav class="desktop-nav" aria-label="Hauptnavigation">
        <NuxtLink v-for="link in links" :key="link.to" :to="link.to">{{
          link.label
        }}</NuxtLink>
      </nav>
      <GlobalPackageSearch compact class="header-search" />
      <div class="header-controls">
        <button
          type="button"
          disabled
          aria-label="Darstellung – nicht verfügbar"
          title="Darstellung nicht verfügbar"
          class="appearance"
        >
          <HubIcon name="sun" /></button
        ><button
          type="button"
          disabled
          aria-label="Sprache Deutsch – Sprachwahl nicht verfügbar"
          class="language"
        >
          DE⌄</button
        ><button
          type="button"
          disabled
          class="login-button"
          title="Anmeldung nicht verfügbar"
        >
          Anmelden
        </button>
      </div>
      <button
        type="button"
        class="mobile-menu-button"
        :aria-expanded="menuOpen"
        aria-controls="mobile-menu"
        aria-label="Navigation öffnen"
        @click="menuOpen = !menuOpen"
      >
        ☰
      </button>
    </div>
    <nav v-if="menuOpen" id="mobile-menu" aria-label="Mobile Navigation">
      <NuxtLink v-for="link in links" :key="link.to" :to="link.to">{{
        link.label
      }}</NuxtLink>
    </nav>
    <SearchCommandPalette />
  </header>
</template>
