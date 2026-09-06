export default defineNuxtPlugin((nuxtApp) => {
  const route = useRoute();
  if (["/email-bestaetigen", "/passwort-zuruecksetzen"].includes(route.path)) {
    // Nuxt normally serializes the full request URL into payload.path. The browser
    // already has the email link; its bearer token must not be copied into HTML.
    nuxtApp.hook("app:rendered", () => {
      nuxtApp.payload.path = route.path;
    });
  }
});
