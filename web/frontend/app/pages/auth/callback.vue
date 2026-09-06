<script setup lang="ts">
import { sanitizeInternalRedirect } from "~/utils/redirect";
const auth = useAuth();
const route = useRoute();
const error = ref("");
useHead({
  title: "Anmeldung · Package Hub",
  meta: [{ name: "robots", content: "noindex" }],
});
onMounted(async () => {
  try {
    await auth.load();
    await navigateTo(
      auth.user.value
        ? sanitizeInternalRedirect(route.query.redirect, "/profil")
        : "/anmelden",
      { replace: true },
    );
  } catch {
    error.value =
      "Die Sitzung kann gerade nicht geladen werden. Bitte erneut versuchen.";
  }
});
</script>
<template>
  <section class="auth-card">
    <h1>Anmeldung</h1>
    <p role="status">{{ error || "Sitzung wird geladen …" }}</p>
    <NuxtLink to="/anmelden">Zur Anmeldung</NuxtLink>
  </section>
</template>
