<script setup lang="ts">
definePageMeta({ middleware: "auth" });
useHead({
  title: "Profil und Sicherheit · Package Hub",
  meta: [{ name: "robots", content: "noindex, nofollow" }],
});
</script>
<template>
  <div class="auth-profile">
    <header class="profile-heading">
      <p class="eyebrow">Konto</p>
      <h1 class="page-title">Profil</h1>
      <p>Persönliche Angaben, Profilbild und verbundene Konten verwalten.</p>
    </header>
    <AuthSecurity />
  </div>
</template>
