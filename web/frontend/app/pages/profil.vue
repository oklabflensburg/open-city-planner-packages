<script setup lang="ts">
definePageMeta({ middleware: "auth" });
useHead({
  title: "Profil und Sicherheit · Package Hub",
  meta: [{ name: "robots", content: "noindex, nofollow" }],
});
</script>
<template>
  <div class="auth-profile">
    <h1 class="page-title">Profil und Sicherheit</h1>
    <AuthSecurity />
  </div>
</template>
