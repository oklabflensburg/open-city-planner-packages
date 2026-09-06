import type { AuthResponse, AuthUser, MfaChallenge } from "~/types/auth";

// Reference refresh/retry and cookie model, with request-local SSR state.
export class AuthError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
  ) {
    super(message);
  }
}

export default defineNuxtPlugin(async () => {
  const config = useRuntimeConfig();
  const enabled =
    config.public.authEnabled === true ||
    String(config.public.authEnabled) === "true";
  const user = useState<AuthUser | null>("auth-user", () => null);
  // Never use Nuxt state for CSRF, challenges, recovery codes, or bearer tokens.
  const challenge = ref<MfaChallenge | null>(null);
  let refreshPromise: Promise<boolean> | null = null;
  let generation = 0;
  const base = import.meta.server ? config.apiBaseInternal : "/api";
  const event = import.meta.server ? useRequestEvent() : undefined;
  const forwardedCookie = import.meta.server
    ? useRequestHeaders(["cookie"]).cookie
    : undefined;

  function apply(result: AuthResponse) {
    // Explicit projection prevents credentials added to future API responses entering SSR payloads.
    const value = result.user;
    user.value = {
      id: value.id,
      email: value.email,
      first_name: value.first_name,
      last_name: value.last_name,
      display_name: value.display_name,
      is_verified: value.is_verified,
      email_pending: value.email_pending,
    };
    challenge.value = null;
  }

  async function raw<T>(path: string, method = "GET", body?: unknown) {
    const headers: Record<string, string> = {};
    if (import.meta.server && forwardedCookie) headers.cookie = forwardedCookie;
    if (import.meta.server && method === "POST")
      headers.origin = config.public.siteUrl;
    if (import.meta.client && method !== "GET") {
      const token = document.cookie
        .split("; ")
        .find((value) => value.startsWith("ocp_hub_csrf_token="));
      if (token)
        headers["x-csrf-token"] = decodeURIComponent(
          token.split("=").slice(1).join("="),
        );
    }
    const response = await $fetch.raw<T>(`${base}/v1${path}`, {
      method: method as "GET" | "POST" | "PATCH" | "DELETE",
      body: body as Record<string, unknown> | undefined,
      headers,
      credentials: "include",
      ignoreResponseError: true,
      retry: 0,
    });
    if (import.meta.server && event) {
      for (const cookie of response.headers.getSetCookie()) {
        event.node.res.appendHeader("set-cookie", cookie);
      }
    }
    if (response.status >= 400) {
      const detail = (
        response._data as {
          detail?: { error?: { code?: string; message?: string } };
        }
      )?.detail;
      if (
        [
          "ACCESS_TOKEN_INVALID",
          "ACCOUNT_SELF_DEACTIVATED",
          "ACCOUNT_DISABLED",
          "REFRESH_TOKEN_INVALID",
          "REFRESH_TOKEN_EXPIRED",
          "SESSION_REVOKED",
          "REFRESH_TOKEN_REUSE_DETECTED",
        ].includes(detail?.error?.code || "")
      ) {
        generation++;
        user.value = null;
        challenge.value = null;
      }
      throw new AuthError(
        detail?.error?.message ||
          "Bitte prüfen Sie Ihre Eingaben oder versuchen Sie es später erneut.",
        detail?.error?.code || "REQUEST_FAILED",
        response.status,
      );
    }
    return response._data as T;
  }

  async function refresh() {
    if (refreshPromise) return refreshPromise;
    const started = generation;
    refreshPromise = (async () => {
      try {
        const result = await raw<AuthResponse>("/auth/refresh", "POST");
        if (started !== generation) return false;
        apply(result);
        return true;
      } catch (error) {
        if (
          error instanceof AuthError &&
          error.code === "REFRESH_ALREADY_ROTATED" &&
          import.meta.client
        ) {
          // Another tab may be completing the reference's rotation grace window.
          for (let i = 0; i < 5; i++) {
            await new Promise((resolve) => setTimeout(resolve, 100));
            try {
              const session = await raw<AuthResponse>("/auth/session");
              if (started !== generation) return false;
              apply(session);
              return true;
            } catch {
              /* retry session lookup, never replay a mutation */
            }
          }
        }
        if (
          started === generation &&
          error instanceof AuthError &&
          [401, 403].includes(error.status)
        )
          user.value = null;
        throw error;
      } finally {
        refreshPromise = null;
      }
    })();
    return refreshPromise;
  }

  async function request<T>(
    path: string,
    method = "GET",
    body?: unknown,
  ): Promise<T> {
    try {
      return await raw<T>(path, method, body);
    } catch (error) {
      const refreshable =
        error instanceof AuthError &&
        ["AUTH_REQUIRED", "ACCESS_TOKEN_EXPIRED"].includes(error.code);
      if (import.meta.client && refreshable && (await refresh()))
        return raw<T>(path, method, body);
      throw error;
    }
  }

  async function load() {
    try {
      const value = await raw<AuthUser>("/auth/me");
      apply({ status: "authenticated", user: value, csrf_token: "" });
    } catch (error) {
      if (error instanceof AuthError && error.status === 401) {
        if (
          import.meta.server &&
          !forwardedCookie?.includes("ocp_hub_refresh_token=")
        ) {
          user.value = null;
          return;
        }
        try {
          await refresh();
        } catch (refreshError) {
          if (
            refreshError instanceof AuthError &&
            [401, 403].includes(refreshError.status)
          ) {
            user.value = null;
            return;
          }
          throw refreshError;
        }
      } else if (error instanceof AuthError && error.status === 403)
        user.value = null;
      else throw error;
    }
  }

  async function login(body: unknown, path = "/auth/login") {
    const result = await raw<AuthResponse | MfaChallenge>(path, "POST", body);
    generation++;
    if (result.status === "mfa_required") {
      user.value = null;
      challenge.value = result;
    } else apply(result);
    return result.status;
  }
  async function logout(all = false) {
    await request(`/auth/${all ? "logout-all" : "logout"}`, "POST");
    generation++;
    user.value = null;
    challenge.value = null;
  }

  if (enabled && import.meta.server && forwardedCookie?.includes("ocp_hub_")) {
    try {
      await load();
    } catch {
      throw createError({
        statusCode: 503,
        statusMessage:
          "Die Sitzung kann gerade nicht geprüft werden. Bitte erneut laden.",
      });
    }
  }
  return {
    provide: {
      auth: { enabled, user, challenge, request, login, logout, load, apply },
    },
  };
});
