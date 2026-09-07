<script setup lang="ts">
import type { ProviderAccount } from "~/types/auth";
import { profileDate, profileUrl } from "~/utils/profile";
const props = defineProps<{
  accounts: ProviderAccount[];
  providers: string[];
  busy: boolean;
}>();
defineEmits<{ unlink: [provider: string] }>();
const rows = computed(() =>
  ["github", "google"].map((id) => ({
    id,
    label: id === "github" ? "GitHub" : "Google",
    account: props.accounts.find((account) => account.provider === id),
    available: props.providers.includes(id),
  })),
);
</script>
<template>
  <section class="auth-card profile-card" aria-labelledby="linked-heading">
    <header>
      <h2 id="linked-heading">Verknüpfte Konten</h2>
      <p>Externe Anmeldungen mit dem lokalen Konto verbinden.</p>
    </header>
    <ul class="profile-list provider-list">
      <li v-for="row in rows" :key="row.id" class="provider-row">
        <span class="provider-icon" aria-hidden="true">
          <HubIcon v-if="row.id === 'github'" name="github" />
          <svg v-else viewBox="0 0 24 24" fill="currentColor">
            <path
              d="M21.6 12.2c0-.7-.1-1.4-.2-2.1H12v4h5.4a4.6 4.6 0 0 1-2 3 6.1 6.1 0 1 1 1-9.7l3-3A10 10 0 1 0 22 12l-.4.2Z"
            />
          </svg>
        </span>
        <div class="provider-details">
          <h3>{{ row.label }}</h3>
          <template v-if="row.account">
            <p>
              {{
                row.account.provider_username ||
                row.account.provider_email ||
                "Verbunden"
              }}
            </p>
            <p
              v-if="row.account.provider_username && row.account.provider_email"
              class="auth-hint"
            >
              {{ row.account.provider_email }}
            </p>
            <span class="profile-status">Verbunden</span>
            <a
              v-if="profileUrl(row.account.provider_profile_url)"
              :href="profileUrl(row.account.provider_profile_url)"
              target="_blank"
              rel="noopener noreferrer"
              class="profile-external"
              >Profil bei {{ row.label }} <HubIcon name="external"
            /></a>
            <p v-if="profileDate(row.account.last_login_at)" class="auth-hint">
              Letzter Login: {{ profileDate(row.account.last_login_at) }}
            </p>
          </template>
          <p v-else>
            {{ busy ? "Verbindung wird geprüft …" : "Nicht verbunden" }}
          </p>
        </div>
        <button
          v-if="row.account"
          type="button"
          class="secondary-button"
          :disabled="busy"
          :aria-label="`${row.label}: Verknüpfung lösen`"
          @click="$emit('unlink', row.id)"
        >
          Verknüpfung lösen
        </button>
        <a
          v-else-if="row.available && !busy"
          class="secondary-button"
          :href="`/api/v1/auth/oauth/${row.id}/link`"
          >{{ row.label }}-Konto verknüpfen</a
        >
        <span v-else-if="!busy" class="auth-hint">Derzeit nicht verfügbar</span>
      </li>
    </ul>
  </section>
</template>
