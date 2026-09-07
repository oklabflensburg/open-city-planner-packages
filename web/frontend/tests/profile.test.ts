import { mountSuspended } from "@nuxt/test-utils/runtime";
import { flushPromises } from "@vue/test-utils";
import { useNuxtApp } from "#app";
import { afterEach, describe, expect, it, vi } from "vitest";
import AuthSecurity from "~/components/AuthSecurity.vue";
import { profileUrl } from "~/utils/profile";
import * as webauthn from "~/utils/webauthn";
const auth = () => useNuxtApp().$auth;
const github = {
  id: "gh",
  provider: "github",
  provider_username: "mara.codes",
  provider_email: "mara@example.org",
  provider_avatar_url: "https://avatars.example.org/mara.png",
  provider_profile_url: "https://github.com/mara",
  last_login_at: "2026-09-01T12:00:00Z",
};
async function profile(
  local = true,
  accounts: any[] = [github],
  enabled = false,
) {
  auth().enabled = true;
  auth().user.value = {
    id: "test",
    email: "mara@example.org",
    display_name: "Mara Hansen",
    first_name: "",
    last_name: "",
    is_verified: true,
    email_pending: false,
    has_local_password: local,
    created_at: "2026-01-05T12:00:00Z",
  };
  vi.spyOn(webauthn, "isPasskeySupported").mockReturnValue(true);
  const request = vi
    .spyOn(auth(), "request")
    .mockImplementation(async (path: string) => {
      if (path === "/auth/providers")
        return { providers: ["github", "google", "mastodon"] } as any;
      if (path === "/users/me/oauth-accounts") return accounts as any;
      if (path === "/auth/mfa/security")
        return { enabled, recovery_codes_remaining: 8 } as any;
      return [] as any;
    });
  const wrapper = await mountSuspended(AuthSecurity);
  await flushPromises();
  return { wrapper, request };
}
afterEach(() => {
  vi.restoreAllMocks();
  auth().enabled = false;
  auth().user.value = null;
});
describe("profile settings", () => {
  it("renders linked metadata, provider avatar and only GitHub / Google", async () => {
    const { wrapper, request } = await profile();
    expect(wrapper.text()).toContain("mara.codes");
    expect(wrapper.text()).not.toContain("Mastodon");
    expect(wrapper.find('[href*="mastodon"]').exists()).toBe(false);
    expect(wrapper.get(".profile-avatar img").attributes("src")).toBe(
      github.provider_avatar_url,
    );
    expect(
      wrapper.get('a[href="/api/v1/auth/oauth/google/link"]').text(),
    ).toContain("Google-Konto verknüpfen");
    await wrapper
      .get('[aria-label="GitHub: Verknüpfung lösen"]')
      .trigger("click");
    await flushPromises();
    expect(request).toHaveBeenCalledWith(
      "/users/me/oauth-accounts/github",
      "DELETE",
    );
    expect(wrapper.get(".profile-metadata").text()).toContain("05.01.2026");
    expect(
      wrapper.get("section:last-child").attributes("aria-labelledby"),
    ).toBe("danger-heading");
  });
  it("handles Google connected and invalid external URLs without unsafe links", async () => {
    const { wrapper } = await profile(false, [
      {
        ...github,
        provider: "google",
        provider_profile_url: "javascript:alert(1)",
        provider_avatar_url: "data:text/html,test",
      },
    ]);
    expect(
      wrapper.find('[aria-label="Google: Verknüpfung lösen"]').exists(),
    ).toBe(true);
    expect(wrapper.find('[href^="javascript:"]').exists()).toBe(false);
    expect(wrapper.find(".profile-avatar img").exists()).toBe(false);
    expect(profileUrl("https://user:password@example.org")).toBeUndefined();
    expect(wrapper.find("#current-password").exists()).toBe(false);
    expect(wrapper.text()).toContain("Lokales Passwort einrichten");
  });
  it("saves the display name with the existing API", async () => {
    const { wrapper, request } = await profile();
    vi.spyOn(auth(), "load").mockResolvedValue(undefined);
    await wrapper.get("#profile-name").setValue("Mara");
    await wrapper
      .get("#profile-name")
      .element.closest("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flushPromises();
    expect(request).toHaveBeenCalledWith("/users/me", "PATCH", {
      display_name: "Mara",
    });
    expect(wrapper.get('[role="status"]').text()).toContain(
      "Profil gespeichert",
    );
  });
  it("keeps password and MFA controls in their own sections", async () => {
    const { wrapper, request } = await profile(true, [], true);
    expect(wrapper.find("#current-password").exists()).toBe(true);
    expect(wrapper.find("#new-password").attributes("autocomplete")).toBe(
      "new-password",
    );
    expect(wrapper.text()).toContain("Authenticator aktiv");
    await wrapper.get("#mfa-password").setValue("LOCAL_PASSWORD_SENTINEL");
    await wrapper.get("#factor-code").setValue("123456");
    request.mockImplementationOnce(
      async () => ({ recovery_codes: ["RECOVERY_SENTINEL"] }) as any,
    );
    await wrapper
      .findAll("button")
      .find((b) => b.text() === "Neue Wiederherstellungscodes")!
      .trigger("click");
    await flushPromises();
    expect(request).toHaveBeenCalledWith("/auth/mfa/recovery-codes", "POST", {
      current_password: "LOCAL_PASSWORD_SENTINEL",
      code: "123456",
    });
    expect(wrapper.text()).toContain("RECOVERY_SENTINEL");
  });
  it("asks for a passkey name only after adding and retains session logout", async () => {
    const { wrapper } = await profile(false, []);
    expect(wrapper.text()).toContain("Nicht eingerichtet");
    expect(wrapper.find("#passkey-name").exists()).toBe(false);
    await wrapper
      .findAll("button")
      .find((b) => b.text() === "Passkey hinzufügen")!
      .trigger("click");
    expect(wrapper.find("#passkey-name").exists()).toBe(true);
    const logout = vi.spyOn(auth(), "logout").mockResolvedValue(undefined);
    await wrapper
      .findAll("button")
      .find((b) => b.text() === "Alle Sitzungen beenden")!
      .trigger("click");
    await flushPromises();
    expect(logout).toHaveBeenCalledWith(true);
  });
  it.each([true, false])(
    "requires explicit deletion confirmation (local password: %s)",
    async (local) => {
      const { wrapper, request } = await profile(local, []);
      expect(wrapper.find("#delete-confirm").exists()).toBe(false);
      await wrapper.get(".profile-danger-button").trigger("click");
      expect(wrapper.find("#delete-password").exists()).toBe(local);
      const submit = wrapper.get("#delete-account .profile-danger-button");
      expect(submit.attributes("disabled")).toBeDefined();
      await wrapper.get("#delete-confirm").setValue("LÖSCHEN");
      if (local)
        await wrapper
          .get("#delete-password")
          .setValue("DELETE_PASSWORD_SENTINEL");
      await wrapper.get("#delete-account").trigger("submit");
      await flushPromises();
      expect(request).toHaveBeenCalledWith("/users/me", "DELETE", {
        confirmation_text: "LÖSCHEN",
        current_password: local ? "DELETE_PASSWORD_SENTINEL" : undefined,
      });
    },
  );
});
