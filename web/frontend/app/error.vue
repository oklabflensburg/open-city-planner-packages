<script setup lang="ts">
defineProps<{ error: { statusCode?: number; statusMessage?: string } }>()
</script>
<template>
  <NuxtLayout
    ><section class="container-shell error-page">
      <h1>
        {{
          error.statusCode === 404
            ? 'Modul oder Seite nicht gefunden'
            : 'Registry API nicht verfügbar'
        }}
      </h1>
      <p>
        {{
          error.statusCode === 404
            ? 'Die angeforderte Ressource ist nicht veröffentlicht.'
            : 'Die Registry konnte nicht geladen werden. Bitte versuche es erneut.'
        }}
      </p>
      <button
        type="button"
        class="primary-button"
        @click="clearError({ redirect: '/packages' })"
      >
        Zur Modulübersicht
      </button>
    </section></NuxtLayout
  >
</template>
