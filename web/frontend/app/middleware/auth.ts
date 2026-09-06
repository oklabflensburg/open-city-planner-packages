import { sanitizeInternalRedirect } from "~/utils/redirect";
export default defineNuxtRouteMiddleware(async (to) => {
  const auth = useAuth();
  if (!auth.enabled) return abortNavigation(createError({ statusCode: 404 }));
  if (import.meta.client && !auth.user.value) await auth.load();
  if (!auth.user.value)
    return navigateTo(
      `/anmelden?redirect=${encodeURIComponent(sanitizeInternalRedirect(to.fullPath))}`,
    );
});
