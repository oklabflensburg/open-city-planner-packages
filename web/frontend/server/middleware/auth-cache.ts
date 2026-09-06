export default defineEventHandler(async (event) => {
  const url = getRequestURL(event);
  const path = url.pathname;
  if (
    ["/email-bestaetigen", "/passwort-zuruecksetzen"].includes(path) &&
    url.searchParams.has("token")
  ) {
    // Keep bearer URLs out of every SSR/error payload, including dependency outages.
    // The fragment stays in the browser and is consumed in client-local form state.
    setResponseHeader(event, "Cache-Control", "private, no-store");
    setResponseHeader(event, "Referrer-Policy", "no-referrer");
    setResponseHeader(
      event,
      "Location",
      `${path}#token=${encodeURIComponent(url.searchParams.get("token") || "")}`,
    );
    setResponseStatus(event, 303);
    return send(event, "");
  }
  if (
    getHeader(event, "cookie")?.includes("ocp_hub_") ||
    /^\/(profil|anmelden|registrieren|passwort-|email-bestaetigen|auth\/)/.test(
      path,
    )
  ) {
    setResponseHeader(event, "Cache-Control", "private, no-store");
    setResponseHeader(event, "Referrer-Policy", "no-referrer");
  }
});
