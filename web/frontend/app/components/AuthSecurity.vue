<script setup lang="ts">
import type {
  AuthResponse,
  MfaStatus,
  Passkey,
  ProviderAccount,
} from "~/types/auth";
import {
  authenticateWithPasskey,
  createPasskey,
  isPasskeySupported,
} from "~/utils/webauthn";
import { profileDate, profileUrl } from "~/utils/profile";
const auth = useAuth();
const { user } = auth;
const error = ref(""),
  message = ref(""),
  busy = ref(false);
const providers = ref<string[]>([]),
  accounts = ref<ProviderAccount[]>([]),
  passkeys = ref<Passkey[]>([]);
const mfa = ref<MfaStatus | null>(null),
  supportsPasskey = ref(false);
const currentPassword = ref(""),
  newPassword = ref(""),
  passwordConfirm = ref("");
const totp = ref<{ secret: string; otpauth_uri: string } | null>(null),
  code = ref(""),
  recoveryCode = ref("");
const recoveryCodes = ref<string[]>([]),
  passkeyName = ref(""),
  email = ref(""),
  displayName = ref(user.value?.display_name || "");
const deletionConfirmation = ref("");
const deletePassword = ref(""),
  mfaPassword = ref("");
const addingPasskey = ref(false),
  avatarFailed = ref(false),
  deleting = ref(false);
const avatar = computed(
  () =>
    profileUrl(user.value?.avatar_url) ||
    accounts.value
      .filter((a) => ["github", "google"].includes(a.provider))
      .map((a) => profileUrl(a.provider_avatar_url))
      .find(Boolean),
);
watch(avatar, () => {
  avatarFailed.value = false;
});
const initials = computed(() =>
  (user.value?.display_name || user.value?.email || "?")
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toLocaleUpperCase("de-DE"),
);
async function unlink(provider: string) {
  if (!["github", "google"].includes(provider)) return;
  await act(async () => {
    await auth.request(`/users/me/oauth-accounts/${provider}`, "DELETE");
  });
}
async function load() {
  const result = await Promise.all([
    auth.request<{ providers: string[] }>("/auth/providers"),
    auth.request<ProviderAccount[]>("/users/me/oauth-accounts"),
    auth.request<Passkey[]>("/users/me/passkeys"),
    auth.request<MfaStatus>("/auth/mfa/security"),
  ]);
  providers.value = result[0].providers;
  accounts.value = result[1];
  passkeys.value = result[2];
  mfa.value = result[3];
}
async function act(action: () => Promise<void>, reload = true) {
  if (busy.value) return;
  error.value = "";
  message.value = "";
  busy.value = true;
  try {
    await action();
    if (reload) await load();
  } catch (cause) {
    error.value =
      cause instanceof Error
        ? cause.message
        : "Die Anfrage ist fehlgeschlagen.";
  } finally {
    busy.value = false;
  }
}
onMounted(() => {
  supportsPasskey.value = isPasskeySupported();
  void act(load, false);
});
async function saveProfile() {
  await act(async () => {
    await auth.request("/users/me", "PATCH", {
      display_name: displayName.value,
    });
    await auth.load();
    message.value = "Profil gespeichert.";
  });
}
async function verifyEmail() {
  await act(async () => {
    const result = await auth.request<{ message: string }>(
      user.value?.email_pending
        ? "/auth/oauth/complete-email"
        : "/auth/resend-verification",
      "POST",
      user.value?.email_pending ? { email: email.value } : undefined,
    );
    message.value = result.message;
    await auth.load();
  });
}
async function changePassword() {
  await act(async () => {
    await auth.request("/auth/change-password", "POST", {
      current_password: currentPassword.value,
      new_password: newPassword.value,
      new_password_confirm: passwordConfirm.value,
    });
    currentPassword.value = "";
    newPassword.value = "";
    passwordConfirm.value = "";
    user.value = null;
    await navigateTo("/anmelden");
  }, false);
}
async function setupTotp() {
  await act(async () => {
    totp.value = await auth.request("/auth/mfa/totp/setup", "POST");
  });
}
async function confirmTotp() {
  await act(async () => {
    recoveryCodes.value = (
      await auth.request<{ recovery_codes: string[] }>(
        "/auth/mfa/totp/confirm",
        "POST",
        { code: code.value },
      )
    ).recovery_codes;
    totp.value = null;
    code.value = "";
  });
}
function factor() {
  return {
    current_password: mfaPassword.value || undefined,
    ...(recoveryCode.value
      ? { recovery_code: recoveryCode.value }
      : { code: code.value }),
  };
}
async function regenerate() {
  await act(async () => {
    recoveryCodes.value = (
      await auth.request<{ recovery_codes: string[] }>(
        "/auth/mfa/recovery-codes",
        "POST",
        factor(),
      )
    ).recovery_codes;
    code.value = "";
    recoveryCode.value = "";
    mfaPassword.value = "";
  });
}
async function disableTotp() {
  await act(async () => {
    await auth.request("/auth/mfa/totp", "DELETE", factor());
    user.value = null;
    recoveryCodes.value = [];
    await navigateTo("/anmelden");
  }, false);
}
async function registerPasskey() {
  await act(async () => {
    const options = await auth.request<{
      ceremony_token: string;
      options: Record<string, any>;
    }>("/auth/passkeys/register/options", "POST");
    const credential = await createPasskey(options.options);
    await auth.request("/auth/passkeys/register/verify", "POST", {
      ceremony_token: options.ceremony_token,
      credential,
      name: passkeyName.value || undefined,
    });
    passkeyName.value = "";
    addingPasskey.value = false;
    message.value = "Passkey hinzugefügt.";
  });
}
async function stepUp() {
  await act(async () => {
    const options = await auth.request<{
      ceremony_token: string;
      options: Record<string, any>;
    }>("/auth/passkeys/reauth/options", "POST");
    const credential = await authenticateWithPasskey(options.options);
    auth.apply(
      await auth.request<AuthResponse>("/auth/passkeys/reauth/verify", "POST", {
        ceremony_token: options.ceremony_token,
        credential,
      }),
    );
    message.value = "Anmeldung erneut bestätigt.";
  });
}
async function endSessions() {
  await act(async () => {
    await auth.logout(true);
    await navigateTo("/anmelden");
  }, false);
}
async function removeAccount() {
  if (deletionConfirmation.value !== "LÖSCHEN") return;
  await act(async () => {
    await auth.request("/users/me", "DELETE", {
      confirmation_text: deletionConfirmation.value,
      current_password: deletePassword.value || undefined,
    });
    user.value = null;
    await navigateTo("/anmelden");
  }, false);
}
</script>
<template>
  <div class="auth-security" :aria-busy="busy">
    <p v-if="error" role="alert" class="auth-error">
      {{ error }}
      <NuxtLink to="/anmelden?redirect=/profil">Erneut anmelden</NuxtLink>
    </p>
    <p v-if="message" role="status" class="auth-message">{{ message }}</p>

    <section
      class="auth-card profile-card profile-avatar-card"
      aria-labelledby="avatar-heading"
    >
      <div class="profile-avatar">
        <img
          v-if="avatar && !avatarFailed"
          :src="avatar"
          alt=""
          referrerpolicy="no-referrer"
          @error="avatarFailed = true"
        />
        <span v-else aria-hidden="true">{{ initials }}</span>
      </div>
      <div>
        <h2 id="avatar-heading">Profilbild</h2>
        <p class="profile-display-name">
          {{ user?.display_name || "Ihr Konto" }}
        </p>
        <p class="auth-hint">
          {{
            avatar && !avatarFailed
              ? "Profilbild aus Ihrem verbundenen Konto."
              : "Ohne Profilbild zeigen wir Ihre Initialen."
          }}
          Ihr Profilbild verwalten Sie bei GitHub oder Google.
        </p>
      </div>
    </section>

    <ProfileLinkedAccounts
      :accounts="accounts"
      :providers="providers"
      :busy="busy"
      @unlink="unlink"
    />

    <section class="auth-card profile-card" aria-labelledby="identity-heading">
      <header>
        <h2 id="identity-heading">Persönliche Angaben</h2>
        <p>Ihre Kontoinformationen und Ihr öffentlicher Anzeigename.</p>
      </header>
      <dl class="profile-metadata">
        <div>
          <dt>E-Mail</dt>
          <dd>
            {{ user?.email_pending ? "Noch nicht hinterlegt" : user?.email }}
          </dd>
        </div>
        <div>
          <dt>E-Mail bestätigt</dt>
          <dd>
            <span
              :class="[
                'profile-status',
                { 'profile-status-pending': !user?.is_verified },
              ]"
              >{{
                user?.is_verified ? "Bestätigt" : "Noch nicht bestätigt"
              }}</span
            >
          </dd>
        </div>
        <div v-if="profileDate(user?.created_at)">
          <dt>Registriert seit</dt>
          <dd>{{ profileDate(user?.created_at) }}</dd>
        </div>
        <div v-if="profileDate(user?.last_login_at)">
          <dt>Letzter Login</dt>
          <dd>{{ profileDate(user?.last_login_at) }}</dd>
        </div>
      </dl>
      <form class="profile-form profile-divider" @submit.prevent="saveProfile">
        <label for="profile-name">Anzeigename</label
        ><input
          id="profile-name"
          v-model="displayName"
          maxlength="180"
          autocomplete="nickname"
        />
        <p class="auth-hint">
          Unter diesem Namen erscheint Ihr Konto im Package Hub.
        </p>
        <button class="primary-button" :disabled="busy">
          Profil speichern
        </button>
      </form>
      <form
        v-if="!user?.is_verified"
        class="profile-form profile-divider"
        @submit.prevent="verifyEmail"
      >
        <template v-if="user?.email_pending"
          ><label for="profile-email">E-Mail ergänzen</label
          ><input
            id="profile-email"
            v-model="email"
            type="email"
            autocomplete="email"
            required
        /></template>
        <p class="auth-hint">
          Bestätigen Sie Ihre E-Mail-Adresse, um Ihr Konto vollständig zu
          nutzen.
        </p>
        <button class="secondary-button" :disabled="busy">
          Bestätigungs-E-Mail senden
        </button>
      </form>
    </section>

    <header class="profile-section-heading">
      <p class="eyebrow">Sicherheit</p>
      <h2>Anmeldung und Kontoschutz</h2>
      <p>Verwalten Sie, wie Sie sich anmelden und Ihr Konto schützen.</p>
    </header>
    <section class="auth-card profile-card" aria-labelledby="password-heading">
      <header>
        <h2 id="password-heading">Passwort</h2>
        <p>
          {{
            user?.has_local_password
              ? "Ein lokales Passwort ist eingerichtet."
              : "Sie können auch ein lokales Passwort für die Anmeldung verwenden."
          }}
        </p>
      </header>
      <details v-if="user?.has_local_password" class="profile-disclosure">
        <summary>Passwort ändern</summary>
        <form class="profile-form" @submit.prevent="changePassword">
          <label for="current-password">Aktuelles Passwort</label
          ><input
            id="current-password"
            v-model="currentPassword"
            type="password"
            autocomplete="current-password"
            maxlength="256"
            required
          />
          <label for="new-password">Neues Passwort</label
          ><input
            id="new-password"
            v-model="newPassword"
            type="password"
            autocomplete="new-password"
            minlength="12"
            maxlength="256"
            required
          />
          <label for="password-confirm">Neues Passwort bestätigen</label
          ><input
            id="password-confirm"
            v-model="passwordConfirm"
            type="password"
            autocomplete="new-password"
            minlength="12"
            maxlength="256"
            required
          />
          <button class="primary-button" :disabled="busy">
            Passwort ändern
          </button>
        </form>
      </details>
      <NuxtLink class="profile-reset" to="/passwort-vergessen">{{
        user?.has_local_password
          ? "Passwort vergessen?"
          : "Lokales Passwort einrichten"
      }}</NuxtLink>
    </section>

    <section class="auth-card profile-card" aria-labelledby="mfa-heading">
      <header class="profile-card-heading">
        <div>
          <h2 id="mfa-heading">Zwei-Faktor-Authentifizierung</h2>
          <p>Ein zusätzlicher Code schützt Ihr Konto bei der Anmeldung.</p>
        </div>
        <span
          v-if="mfa"
          :class="[
            'profile-status',
            { 'profile-status-pending': !mfa.enabled },
          ]"
          >{{ mfa.enabled ? "Aktiv" : "Nicht eingerichtet" }}</span
        >
      </header>
      <p v-if="!mfa" class="auth-hint">Sicherheitsstatus wird geladen …</p>
      <button
        v-if="mfa && !mfa.enabled && !totp"
        :disabled="busy"
        class="secondary-button"
        @click="setupTotp"
      >
        Authenticator einrichten
      </button>
      <form v-if="totp" class="profile-form" @submit.prevent="confirmTotp">
        <p>Hinterlegen Sie diesen Schlüssel in Ihrer Authenticator-App:</p>
        <code class="auth-secret">{{ totp.secret }}</code>
        <label for="setup-code">Authenticator-Code</label
        ><input
          id="setup-code"
          v-model="code"
          inputmode="numeric"
          autocomplete="one-time-code"
          pattern="[0-9]{6}"
          required
        />
        <button :disabled="busy" class="primary-button">
          Einrichtung bestätigen
        </button>
      </form>
      <template v-if="mfa?.enabled">
        <p>
          Authenticator aktiv · {{ mfa.recovery_codes_remaining }} unbenutzte
          Wiederherstellungscodes.
        </p>
        <details class="profile-disclosure">
          <summary>Wiederherstellung und Authenticator verwalten</summary>
          <div class="profile-form">
            <template v-if="user?.has_local_password"
              ><label for="mfa-password"
                >Aktuelles Passwort für die Sicherheitsänderung</label
              ><input
                id="mfa-password"
                v-model="mfaPassword"
                type="password"
                autocomplete="current-password"
                maxlength="256"
            /></template>
            <label for="factor-code">Authenticator-Code</label
            ><input
              id="factor-code"
              v-model="code"
              inputmode="numeric"
              autocomplete="one-time-code"
            />
            <label for="recovery-code">Oder Wiederherstellungscode</label
            ><input
              id="recovery-code"
              v-model="recoveryCode"
              autocomplete="off"
            />
            <div class="profile-actions">
              <button
                :disabled="busy"
                class="secondary-button"
                @click="regenerate"
              >
                Neue Wiederherstellungscodes</button
              ><button
                :disabled="busy"
                class="secondary-button"
                @click="disableTotp"
              >
                Authenticator deaktivieren
              </button>
            </div>
          </div>
        </details>
      </template>
      <div v-if="recoveryCodes.length" role="status" class="profile-divider">
        <h3>Wiederherstellungscodes sicher aufbewahren</h3>
        <p>
          Diese Codes werden nur jetzt angezeigt. Jeder Code funktioniert
          einmal.
        </p>
        <ul class="auth-secret">
          <li v-for="value in recoveryCodes" :key="value">{{ value }}</li>
        </ul>
        <button class="secondary-button" @click="recoveryCodes = []">
          Sicher aufbewahrt
        </button>
      </div>
    </section>

    <section class="auth-card profile-card" aria-labelledby="passkeys-heading">
      <header>
        <h2 id="passkeys-heading">Passkeys</h2>
        <p>Mit Passkeys können Sie sich ohne Passwort sicher anmelden.</p>
      </header>
      <p v-if="!supportsPasskey" class="auth-hint">
        Passkeys benötigen einen unterstützten Browser und eine sichere
        Verbindung.
      </p>
      <ul v-if="passkeys.length" class="profile-list">
        <li v-for="key in passkeys" :key="key.id" class="profile-passkey">
          <details class="profile-disclosure">
            <summary>{{ key.name }}</summary>
            <p v-if="profileDate(key.last_used_at)" class="auth-hint">
              Zuletzt verwendet: {{ profileDate(key.last_used_at) }}
            </p>
            <form
              class="profile-form"
              @submit.prevent="
                act(async () => {
                  await auth.request(`/users/me/passkeys/${key.id}`, 'PATCH', {
                    name: key.name,
                  });
                })
              "
            >
              <label :for="`key-${key.id}`">Passkey-Name</label
              ><input
                :id="`key-${key.id}`"
                v-model="key.name"
                required
                maxlength="120"
              />
              <div class="profile-actions">
                <button :disabled="busy" class="secondary-button">
                  Umbenennen</button
                ><button
                  type="button"
                  :disabled="busy"
                  class="secondary-button"
                  @click="
                    act(async () => {
                      await auth.request(
                        `/users/me/passkeys/${key.id}`,
                        'DELETE',
                      );
                    })
                  "
                >
                  Passkey entfernen
                </button>
              </div>
            </form>
          </details>
        </li>
      </ul>
      <p v-else-if="!busy" class="auth-hint">Noch keine Passkeys hinterlegt.</p>
      <button
        v-if="supportsPasskey && !addingPasskey"
        class="secondary-button"
        :disabled="busy"
        aria-controls="passkey-add"
        :aria-expanded="addingPasskey"
        @click="addingPasskey = true"
      >
        Passkey hinzufügen
      </button>
      <form
        v-if="supportsPasskey && addingPasskey"
        id="passkey-add"
        class="profile-form"
        @submit.prevent="registerPasskey"
      >
        <label for="passkey-name">Name des neuen Passkeys</label
        ><input
          id="passkey-name"
          v-model="passkeyName"
          maxlength="120"
          placeholder="Zum Beispiel: Mein Laptop"
        />
        <div class="profile-actions">
          <button class="primary-button" :disabled="busy">
            Passkey hinzufügen</button
          ><button
            type="button"
            class="secondary-button"
            :disabled="busy"
            @click="
              addingPasskey = false;
              passkeyName = '';
            "
          >
            Abbrechen
          </button>
        </div>
      </form>
      <button
        v-if="supportsPasskey && passkeys.length"
        class="secondary-button"
        :disabled="busy"
        @click="stepUp"
      >
        Mit Passkey erneut bestätigen
      </button>
    </section>

    <section class="auth-card profile-card" aria-labelledby="sessions-heading">
      <header>
        <h2 id="sessions-heading">Sitzungen</h2>
        <p>Verwalten Sie aktive Anmeldungen auf Ihren Geräten.</p>
      </header>
      <p class="auth-hint">
        Sie werden auf allen Geräten abgemeldet, auch in diesem Browser.
      </p>
      <button class="secondary-button" :disabled="busy" @click="endSessions">
        Alle Sitzungen beenden
      </button>
    </section>

    <section
      class="auth-card profile-card profile-danger"
      aria-labelledby="danger-heading"
    >
      <header>
        <h2 id="danger-heading">Gefahrenbereich</h2>
        <p>
          Hier kann das Konto dauerhaft entfernt werden. Prüfen Sie sorgfältig,
          welche Aktion Sie auswählen.
        </p>
      </header>
      <div class="profile-danger-inner">
        <h3>Konto dauerhaft löschen</h3>
        <p>
          Ihr Konto, Ihre Anmeldemethoden und Sitzungen werden dauerhaft
          gelöscht. Diese Aktion kann nicht rückgängig gemacht werden.
        </p>
        <button
          v-if="!deleting"
          class="profile-danger-button"
          :disabled="busy"
          aria-controls="delete-account"
          :aria-expanded="deleting"
          @click="deleting = true"
        >
          Konto dauerhaft löschen
        </button>
        <form
          v-if="deleting"
          id="delete-account"
          class="profile-form"
          @submit.prevent="removeAccount"
        >
          <template v-if="user?.has_local_password"
            ><label for="delete-password"
              >Aktuelles Passwort zur Kontolöschung</label
            ><input
              id="delete-password"
              v-model="deletePassword"
              type="password"
              autocomplete="current-password"
              maxlength="256"
              required
          /></template>
          <p v-else class="auth-hint">
            Für die Löschung ist eine kürzlich bestätigte Anmeldung
            erforderlich.
          </p>
          <label for="delete-confirm">Zur Bestätigung LÖSCHEN eingeben</label
          ><input
            id="delete-confirm"
            v-model="deletionConfirmation"
            autocomplete="off"
            required
          />
          <div class="profile-actions">
            <button
              class="profile-danger-button"
              :disabled="busy || deletionConfirmation !== 'LÖSCHEN'"
            >
              Konto endgültig löschen</button
            ><button
              type="button"
              class="secondary-button"
              :disabled="busy"
              @click="
                deleting = false;
                deletionConfirmation = '';
                deletePassword = '';
              "
            >
              Abbrechen
            </button>
          </div>
        </form>
      </div>
    </section>
  </div>
</template>
