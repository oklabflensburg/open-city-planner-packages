<script setup lang="ts">
import type { MfaChallenge } from "~/types/auth";
const auth = useAuth();
const error = ref("");
useHead({
  title: "Anmeldung bestätigen · Package Hub",
  meta: [{ name: "robots", content: "noindex" }],
});
onMounted(async () => {
  try {
    auth.challenge.value = {
      ...(await auth.request<MfaChallenge>("/auth/mfa/challenge")),
      status: "mfa_required",
    };
  } catch {
    error.value =
      "Die Anmeldung ist abgelaufen. Bitte melden Sie sich erneut an.";
  }
});
</script>
<template>
  <section v-if="error" class="auth-card">
    <p role="alert">{{ error }}</p>
    <NuxtLink to="/anmelden">Erneut anmelden</NuxtLink>
  </section>
  <AuthForm v-else mode="login" />
</template>
