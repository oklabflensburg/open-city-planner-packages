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
    current_password: currentPassword.value || undefined,
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
    currentPassword.value = "";
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
  await act(async () => {
    await auth.request("/users/me", "DELETE", {
      confirmation_text: deletionConfirmation.value,
      current_password: currentPassword.value || undefined,
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
    <section class="auth-card">
      <h2>Account</h2>
      <p>{{ user?.email_pending ? "E-Mail noch ergänzen" : user?.email }}</p>
      <p>
        {{
          user?.is_verified ? "E-Mail bestätigt" : "E-Mail noch nicht bestätigt"
        }}
      </p>
      <form @submit.prevent="saveProfile">
        <label for="profile-name">Anzeigename</label
        ><input
          id="profile-name"
          v-model="displayName"
          maxlength="180"
        /><button class="secondary-button" :disabled="busy">
          Profil speichern
        </button>
      </form>
      <form v-if="!user?.is_verified" @submit.prevent="verifyEmail">
        <template v-if="user?.email_pending"
          ><label for="profile-email">E-Mail</label
          ><input id="profile-email" v-model="email" type="email" required
        /></template>
        <button class="secondary-button" :disabled="busy">
          Bestätigungs-E-Mail senden
        </button>
      </form>
    </section>
    <section class="auth-card">
      <h2>Anmeldemethoden</h2>
      <div v-for="provider in providers" :key="provider" class="auth-row">
        <span>{{ provider === "github" ? "GitHub" : "Google" }}</span>
        <button
          v-if="accounts.some((a) => a.provider === provider)"
          :disabled="busy"
          class="secondary-button"
          @click="
            act(async () => {
              await auth.request(
                `/users/me/oauth-accounts/${provider}`,
                'DELETE',
              );
            })
          "
        >
          Verknüpfung entfernen
        </button>
        <a
          v-else
          class="secondary-button"
          :href="`/api/v1/auth/oauth/${provider}/link`"
          >Verknüpfen</a
        >
      </div>
      <h3>Passwort ändern</h3>
      <form @submit.prevent="changePassword">
        <label for="current-password">Aktuelles Passwort</label
        ><input
          id="current-password"
          v-model="currentPassword"
          type="password"
          autocomplete="current-password"
          maxlength="256"
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
        <button class="primary-button" :disabled="busy">Passwort ändern</button>
      </form>
      <NuxtLink to="/passwort-vergessen"
        >Passwort vergessen oder erstmals einrichten</NuxtLink
      >
    </section>
    <section class="auth-card">
      <h2>Zwei-Faktor-Authentifizierung</h2>
      <p v-if="mfa">
        {{
          mfa.enabled
            ? "Authenticator aktiv"
            : "Authenticator noch nicht eingerichtet"
        }}
      </p>
      <button
        v-if="mfa && !mfa.enabled && !totp"
        :disabled="busy"
        class="secondary-button"
        @click="setupTotp"
      >
        Authenticator einrichten
      </button>
      <form v-if="totp" @submit.prevent="confirmTotp">
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
          {{ mfa.recovery_codes_remaining }} unbenutzte Wiederherstellungscodes.
        </p>
        <label for="factor-code">Authenticator-Code</label
        ><input
          id="factor-code"
          v-model="code"
          inputmode="numeric"
          autocomplete="one-time-code"
        />
        <label for="recovery-code">Oder Wiederherstellungscode</label
        ><input id="recovery-code" v-model="recoveryCode" autocomplete="off" />
        <p class="auth-hint">
          Bei lokalem Passwort tragen Sie oben zusätzlich Ihr aktuelles Passwort
          ein.
        </p>
        <button :disabled="busy" class="secondary-button" @click="regenerate">
          Neue Wiederherstellungscodes
        </button>
        <button :disabled="busy" class="secondary-button" @click="disableTotp">
          Authenticator deaktivieren
        </button>
      </template>
      <div v-if="recoveryCodes.length" role="status">
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
    <section class="auth-card">
      <h2>Passkeys</h2>
      <p v-if="!supportsPasskey">
        Passkeys benötigen einen unterstützten Browser und eine sichere
        Verbindung.
      </p>
      <form v-if="supportsPasskey" @submit.prevent="registerPasskey">
        <label for="passkey-name">Name des neuen Passkeys</label
        ><input
          id="passkey-name"
          v-model="passkeyName"
          maxlength="120"
        /><button class="secondary-button" :disabled="busy">
          Passkey hinzufügen
        </button>
      </form>
      <div v-for="key in passkeys" :key="key.id" class="auth-row">
        <form
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
          <button :disabled="busy" class="secondary-button">Umbenennen</button>
        </form>
        <button
          :disabled="busy"
          class="secondary-button"
          @click="
            act(async () => {
              await auth.request(`/users/me/passkeys/${key.id}`, 'DELETE');
            })
          "
        >
          Passkey entfernen
        </button>
      </div>
      <button
        v-if="supportsPasskey && passkeys.length"
        class="secondary-button"
        :disabled="busy"
        @click="stepUp"
      >
        Mit Passkey erneut bestätigen
      </button>
    </section>
    <section class="auth-card">
      <h2>Sitzungen</h2>
      <p>Beenden Sie Ihre Anmeldung auf allen Geräten.</p>
      <button class="secondary-button" :disabled="busy" @click="endSessions">
        Alle Sitzungen beenden
      </button>
    </section>
    <section class="auth-card">
      <h2>Account löschen</h2>
      <p>
        Account, Anmeldemethoden und Sitzungen werden dauerhaft gelöscht. Tragen
        Sie bei lokalem Passwort oben Ihr aktuelles Passwort ein.
      </p>
      <form @submit.prevent="removeAccount">
        <label for="delete-confirm">Zur Bestätigung LÖSCHEN eingeben</label
        ><input
          id="delete-confirm"
          v-model="deletionConfirmation"
          required
        /><button
          class="secondary-button"
          :disabled="busy || deletionConfirmation !== 'LÖSCHEN'"
        >
          Account dauerhaft löschen
        </button>
      </form>
    </section>
  </div>
</template>
