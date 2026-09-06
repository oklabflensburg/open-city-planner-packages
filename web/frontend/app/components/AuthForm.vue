<script setup lang="ts">
import type { AuthResponse } from "~/types/auth";
import { authenticateWithPasskey, isPasskeySupported } from "~/utils/webauthn";
import { sanitizeInternalRedirect } from "~/utils/redirect";
const props = defineProps<{
  mode: "login" | "signup" | "forgot" | "reset" | "verify";
}>();
const auth = useAuth();
const route = useRoute();
const email = ref(""),
  password = ref(""),
  confirmation = ref(""),
  code = ref("");
const token = ref(""),
  error = ref(""),
  message = ref(""),
  busy = ref(false);
const providers = ref<string[]>([]),
  supportsPasskey = ref(false);
const factor = ref("totp");
const titles = {
  login: "Anmelden",
  signup: "Registrieren",
  forgot: "Passwort vergessen?",
  reset: "Passwort zurücksetzen",
  verify: "E-Mail bestätigen",
};
const redirect = () =>
  sanitizeInternalRedirect(route.query.redirect, "/profil");
const challenge = auth.challenge;
watch(challenge, (value) => {
  factor.value = value?.methods.includes("totp") ? "totp" : "recovery_code";
});
const oauthErrors: Record<string, string> = {
  OAUTH_EMAIL_CONFLICT:
    "Diese E-Mail gehört zu einem vorhandenen Account. Bitte zuerst anmelden und den Provider im Profil verknüpfen.",
  INVALID_OAUTH_STATE:
    "Die Anmeldung ist abgelaufen oder ungültig. Bitte erneut beginnen.",
  OAUTH_ACCESS_DENIED: "Die Anmeldung beim Anbieter wurde abgebrochen.",
};
if (typeof route.query.auth_error === "string")
  error.value =
    oauthErrors[route.query.auth_error] ||
    "Die Anmeldung beim Anbieter ist fehlgeschlagen.";
onMounted(async () => {
  supportsPasskey.value = isPasskeySupported();
  if (["reset", "verify"].includes(props.mode)) {
    token.value =
      new URLSearchParams(window.location.hash.slice(1)).get("token") ||
      (typeof route.query.token === "string" ? route.query.token : "");
    if (token.value)
      await navigateTo({ path: route.path, query: {} }, { replace: true });
  }
  if (auth.enabled) {
    try {
      providers.value = (
        await auth.request<{ providers: string[] }>("/auth/providers")
      ).providers;
    } catch {
      error.value = "Anmeldemöglichkeiten können gerade nicht geladen werden.";
    }
  }
});
async function perform(action: () => Promise<void>) {
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    await action();
  } catch (cause) {
    error.value =
      cause instanceof Error
        ? cause.message
        : "Die Anfrage ist fehlgeschlagen.";
  } finally {
    busy.value = false;
  }
}
async function submit() {
  await perform(async () => {
    if (challenge.value) {
      const result = await auth.request<AuthResponse>(
        "/auth/mfa/verify",
        "POST",
        {
          challenge_token: challenge.value.challenge_token,
          ...(factor.value === "recovery_code"
            ? { recovery_code: code.value }
            : { code: code.value }),
        },
      );
      auth.apply(result);
      code.value = "";
      await navigateTo(redirect());
      return;
    }
    if (props.mode === "login" || props.mode === "signup") {
      if (props.mode === "signup" && password.value !== confirmation.value)
        throw new Error("Die Passwörter stimmen nicht überein.");
      const status = await auth.login(
        { email: email.value, password: password.value },
        props.mode === "signup" ? "/auth/signup" : "/auth/login",
      );
      password.value = "";
      confirmation.value = "";
      if (status === "authenticated") await navigateTo(redirect());
    } else if (props.mode === "forgot") {
      message.value = (
        await auth.request<{ message: string }>(
          "/auth/forgot-password",
          "POST",
          { email: email.value },
        )
      ).message;
    } else if (props.mode === "reset") {
      if (!token.value)
        throw new Error(
          "Der Link ist unvollständig. Bitte fordern Sie einen neuen Link an.",
        );
      message.value = (
        await auth.request<{ message: string }>(
          "/auth/reset-password",
          "POST",
          {
            token: token.value,
            password: password.value,
            password_confirm: confirmation.value,
          },
        )
      ).message;
      token.value = "";
      password.value = "";
      confirmation.value = "";
    } else {
      if (!token.value)
        throw new Error(
          "Der Link ist unvollständig. Bitte öffnen Sie den Link aus Ihrer E-Mail.",
        );
      message.value = (
        await auth.request<{ message: string }>("/auth/verify-email", "POST", {
          token: token.value,
        })
      ).message;
      token.value = "";
    }
  });
}
async function passkey() {
  await perform(async () => {
    const mfa = challenge.value;
    const path = mfa ? "/auth/mfa/passkey" : "/auth/passkeys/login";
    const options = await auth.request<{
      ceremony_token: string;
      options: Record<string, any>;
    }>(
      `${path}/options`,
      "POST",
      mfa ? { challenge_token: mfa.challenge_token } : undefined,
    );
    const credential = await authenticateWithPasskey(options.options);
    const result = await auth.request<AuthResponse>(`${path}/verify`, "POST", {
      ceremony_token: options.ceremony_token,
      credential,
      ...(mfa ? { challenge_token: mfa.challenge_token } : {}),
    });
    auth.apply(result);
    await navigateTo(redirect());
  });
}
</script>
<template>
  <section class="auth-card" :aria-busy="busy">
    <h1>{{ challenge ? "Anmeldung bestätigen" : titles[mode] }}</h1>
    <p v-if="!auth.enabled" role="status">
      Die Anmeldung ist noch nicht freigeschaltet.
    </p>
    <template v-else>
      <p v-if="error" role="alert" class="auth-error">{{ error }}</p>
      <p v-if="message" role="status" class="auth-message">{{ message }}</p>
      <form
        v-if="
          !challenge || challenge.methods.some((method) => method !== 'passkey')
        "
        @submit.prevent="submit"
      >
        <template v-if="challenge">
          <label for="auth-factor">Anmeldemethode</label>
          <select id="auth-factor" v-model="factor">
            <option v-if="challenge.methods.includes('totp')" value="totp">
              Authenticator-Code
            </option>
            <option
              v-if="challenge.methods.includes('recovery_code')"
              value="recovery_code"
            >
              Wiederherstellungscode
            </option>
          </select>
          <label for="auth-code">{{
            factor === "recovery_code"
              ? "Wiederherstellungscode"
              : "Authenticator-Code"
          }}</label>
          <input
            id="auth-code"
            v-model="code"
            autocomplete="one-time-code"
            required
            :inputmode="factor === 'totp' ? 'numeric' : 'text'"
          />
        </template>
        <template v-else>
          <template v-if="['login', 'signup', 'forgot'].includes(mode)">
            <label for="auth-email">E-Mail</label
            ><input
              id="auth-email"
              v-model="email"
              type="email"
              autocomplete="username"
              required
              maxlength="320"
            />
          </template>
          <template v-if="['login', 'signup', 'reset'].includes(mode)">
            <label for="auth-password">Passwort</label
            ><input
              id="auth-password"
              v-model="password"
              type="password"
              :autocomplete="
                mode === 'login' ? 'current-password' : 'new-password'
              "
              required
              :minlength="mode === 'login' ? undefined : 12"
              maxlength="256"
            />
            <p v-if="mode !== 'login'" class="auth-hint">
              Mindestens 12 Zeichen.
            </p>
          </template>
          <template v-if="['signup', 'reset'].includes(mode)">
            <label for="auth-confirm">Passwort bestätigen</label
            ><input
              id="auth-confirm"
              v-model="confirmation"
              type="password"
              autocomplete="new-password"
              required
              minlength="12"
              maxlength="256"
            />
          </template>
        </template>
        <button class="primary-button" :disabled="busy">
          {{
            challenge
              ? "Bestätigen"
              : mode === "forgot"
                ? "Link anfordern"
                : titles[mode]
          }}
        </button>
      </form>
      <button
        v-if="
          supportsPasskey &&
          (mode === 'login' || challenge) &&
          (!challenge || challenge.methods.includes('passkey'))
        "
        class="secondary-button"
        :disabled="busy"
        @click="passkey"
      >
        Mit Passkey anmelden
      </button>
      <div
        v-if="['login', 'signup'].includes(mode) && !challenge"
        class="auth-providers"
      >
        <a
          v-for="provider in providers"
          :key="provider"
          class="secondary-button"
          :href="`/api/v1/auth/oauth/${provider}/login?redirect=${encodeURIComponent(redirect())}`"
          >Mit {{ provider === "github" ? "GitHub" : "Google" }} anmelden</a
        >
      </div>
      <nav class="auth-links" aria-label="Konto">
        <NuxtLink v-if="mode === 'login'" to="/passwort-vergessen"
          >Passwort vergessen?</NuxtLink
        >
        <NuxtLink v-if="mode === 'login'" to="/registrieren"
          >Noch kein Konto? Registrieren</NuxtLink
        >
        <NuxtLink v-else to="/anmelden">Zur Anmeldung</NuxtLink>
      </nav>
    </template>
  </section>
</template>
