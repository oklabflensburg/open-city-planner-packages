import { mountSuspended } from "@nuxt/test-utils/runtime";
import { flushPromises } from "@vue/test-utils";
import { useNuxtApp } from "#app";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import AuthForm from "~/components/AuthForm.vue";
import AuthSecurity from "~/components/AuthSecurity.vue";
import AppHeader from "~/components/AppHeader.vue";

const account = {
  id: "test-user",
  email: "test@example.org",
  display_name: "Test User",
  first_name: "",
  last_name: "",
  is_verified: true,
  email_pending: false,
};
const auth = () => useNuxtApp().$auth;
beforeEach(() => {
  auth().enabled = true;
  auth().user.value = null;
  auth().challenge.value = null;
});
afterEach(() => {
  vi.restoreAllMocks();
  auth().enabled = false;
  auth().user.value = null;
  auth().challenge.value = null;
});

async function form(
  mode: "login" | "signup" | "forgot" | "reset" | "verify",
  providers: string[] = [],
) {
  vi.spyOn(auth(), "request").mockResolvedValue({ providers });
  const wrapper = await mountSuspended(AuthForm, { props: { mode } });
  await flushPromises();
  return wrapper;
}

describe("Package Hub authentication", () => {
  it("renders only configured providers and accessible login fields", async () => {
    const wrapper = await form("login", ["github", "google"]);
    expect(wrapper.get('label[for="auth-email"]').text()).toBe("E-Mail");
    expect(wrapper.get("#auth-password").attributes("autocomplete")).toBe(
      "current-password",
    );
    expect(wrapper.findAll(".auth-providers a").map((a) => a.text())).toEqual([
      "Mit GitHub anmelden",
      "Mit Google anmelden",
    ]);
  });
  it("does not invent buttons for disabled providers", async () => {
    const wrapper = await form("login");
    expect(wrapper.findAll(".auth-providers a")).toHaveLength(0);
  });
  it("submits credentials and displays API errors", async () => {
    const login = vi
      .spyOn(auth(), "login")
      .mockRejectedValue(new Error("Ungültige Zugangsdaten."));
    const wrapper = await form("login");
    await wrapper.get("#auth-email").setValue("test@example.org");
    await wrapper.get("#auth-password").setValue("NOT_A_SECRET_TEST_SENTINEL");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(login).toHaveBeenCalledWith(
      { email: "test@example.org", password: "NOT_A_SECRET_TEST_SENTINEL" },
      "/auth/login",
    );
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "Ungültige Zugangsdaten",
    );
  });
  it("validates signup confirmation before creating an account", async () => {
    const login = vi.spyOn(auth(), "login");
    const wrapper = await form("signup");
    await wrapper.get("#auth-password").setValue("NOT_A_SECRET_TEST_SENTINEL");
    await wrapper
      .get("#auth-confirm")
      .setValue("NOT_A_SECRET_DIFFERENT_SENTINEL");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(login).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "stimmen nicht überein",
    );
  });
  it("shows the generic forgot-password acknowledgement", async () => {
    const wrapper = await form("forgot");
    vi.spyOn(auth(), "request").mockResolvedValue({
      message: "Wenn ein Konto existiert, wurde eine E-Mail versendet.",
    });
    await wrapper.get("#auth-email").setValue("test@example.org");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.get('[role="status"]').text()).toContain(
      "Wenn ein Konto existiert",
    );
  });
  it("renders an MFA challenge without displaying its token", async () => {
    auth().challenge.value = {
      status: "mfa_required",
      challenge_token: "PRIVATE_CHALLENGE_SENTINEL",
      methods: ["totp", "recovery_code"],
      preferred_method: "totp",
      expires_in: 300,
    };
    const wrapper = await form("login");
    expect(wrapper.text()).toContain("Anmeldung bestätigen");
    expect(wrapper.find("#auth-factor").exists()).toBe(true);
    expect(wrapper.html()).not.toContain("PRIVATE_CHALLENGE_SENTINEL");
  });
  it("shows authenticated header and performs logout", async () => {
    auth().user.value = account;
    const logout = vi.spyOn(auth(), "logout").mockResolvedValue(undefined);
    const wrapper = await mountSuspended(AppHeader);
    expect(wrapper.text()).toContain("Test User");
    expect(wrapper.find('a[href="/profil"]').exists()).toBe(true);
    await wrapper.get("button.auth-header-link").trigger("click");
    await flushPromises();
    expect(logout).toHaveBeenCalledOnce();
  });
  it("renders profile MFA, passkey and session management", async () => {
    auth().user.value = account;
    vi.spyOn(auth(), "request").mockImplementation(async (path: string) => {
      if (path === "/auth/providers") return { providers: ["github"] } as any;
      if (path === "/auth/mfa/security")
        return { enabled: true, recovery_codes_remaining: 8 } as any;
      return [] as any;
    });
    const wrapper = await mountSuspended(AuthSecurity);
    await flushPromises();
    expect(wrapper.text()).toContain("E-Mail bestätigt");
    expect(wrapper.text()).toContain("Authenticator aktiv");
    expect(wrapper.text()).toContain("8 unbenutzte Wiederherstellungscodes");
    expect(wrapper.text()).toContain("Passkeys");
    expect(wrapper.text()).toContain("Alle Sitzungen beenden");
  });
});

it("clears client identity after a definitive account rejection", async () => {
  auth().user.value = account;
  vi.spyOn(globalThis.$fetch, "raw").mockResolvedValue({
    status: 403,
    headers: new Headers(),
    _data: {
      detail: {
        error: { code: "ACCOUNT_DISABLED", message: "Account deaktiviert." },
      },
    },
  } as any);
  await expect(auth().request("/users/me")).rejects.toThrow(
    "Account deaktiviert.",
  );
  expect(auth().user.value).toBeNull();
});
