<template>
  <footer class="hub-footer">
    <div class="container-shell footer-grid">
      <div class="footer-brand">
        <NuxtLink to="/" class="hub-brand"
          ><img src="/logo.svg" width="37" height="45" alt="" /><span
            ><strong>Open City Planner</strong><span>Package Hub</span></span
          ></NuxtLink
        >
        <p>Modulare Werkzeuge für lebenswerte Städte.</p>
        <p class="copyright">
          © {{ new Date().getUTCFullYear() }} Open City Planner. Ein Projekt
          von <a href="https://oklabflensburg.de">oklabflensburg</a>.
        </p>
      </div>
      <nav aria-label="Entdecken">
        <strong>Entdecken</strong><NuxtLink to="/packages">Module</NuxtLink
        ><NuxtLink to="/publishers">Publisher</NuxtLink
        ><a
          href="https://github.com/oklabflensburg/open-city-planner-packages/releases"
          >Changelog</a
        >
      </nav>
      <nav aria-label="Ressourcen">
        <strong>Ressourcen</strong><NuxtLink to="/docs">Dokumentation</NuxtLink
        ><a
          href="https://github.com/oklabflensburg/open-city-planner-packages/blob/main/docs/registry-api-v2.md"
          >API</a
        ><NuxtLink to="/docs#beispiele">Beispiele</NuxtLink
        ><a
          href="https://github.com/oklabflensburg/open-city-planner-packages/issues"
          >Support</a
        >
      </nav>
      <nav aria-label="Community">
        <strong>Community</strong
        ><a href="https://github.com/oklabflensburg/open-city-planner-packages"
          >GitHub</a
        ><a
          href="https://github.com/oklabflensburg/open-city-planner-packages/issues"
          >Diskussionen</a
        ><a
          href="https://github.com/oklabflensburg/open-city-planner-packages/blob/main/docs/publishing.md"
          >Mitmachen</a
        >
      </nav>
      <div class="footer-right">
        <strong>Gemeinsam bessere Städte.</strong>
        <div class="social-links">
          <a
            href="https://github.com/oklabflensburg"
            aria-label="OK Lab Flensburg auf GitHub"
            ><HubIcon name="github"
          /></a>
          <span
            role="img"
            aria-label="Bluesky – nicht verfügbar"
            aria-disabled="true"
            title="Bluesky – nicht verfügbar"
          >
            <svg
              class="hub-icon"
              viewBox="0 0 24 24"
              fill="currentColor"
              aria-hidden="true"
            >
              <path
                d="M12 10.5C10.2 7 5.4 2.5 2.8 2.5 1.2 2.5 1 4 1 5.2c0 2.3.3 5.3 1 6.3.8 1.2 2.7 1.6 4.5 1.3-3.4.6-4.3 2.5-2.4 4.8 3.5 4.1 6.7-1.3 7.9-3.5 1.2 2.2 4.4 7.6 7.9 3.5 1.9-2.3 1-4.2-2.4-4.8 1.8.3 3.7-.1 4.5-1.3.7-1 1-4 1-6.3 0-1.2-.2-2.7-1.8-2.7-2.6 0-7.4 4.5-9.2 8Z"
              />
            </svg>
          </span>
          <span
            role="img"
            aria-label="LinkedIn – nicht verfügbar"
            aria-disabled="true"
            title="LinkedIn – nicht verfügbar"
          >
            <svg class="hub-icon" viewBox="0 0 24 24" aria-hidden="true">
              <rect
                x="1"
                y="1"
                width="22"
                height="22"
                rx="2"
                fill="currentColor"
              />
              <path
                d="M5 10h3v9H5Zm6 0h3v1.3c.7-1 1.6-1.5 2.8-1.5 2.4 0 3.2 1.6 3.2 4V19h-3v-4.6c0-1.3-.3-2-1.4-2-1.2 0-1.6.8-1.6 2V19h-3Z"
                fill="white"
              />
              <circle cx="6.5" cy="6.5" r="1.7" fill="white" />
            </svg>
          </span>
          <span
            role="img"
            aria-label="RSS – nicht verfügbar"
            aria-disabled="true"
            title="RSS – nicht verfügbar"
          >
            <svg
              class="hub-icon"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden="true"
            >
              <circle cx="5" cy="19" r="2" fill="currentColor" />
              <path
                d="M3 10a11 11 0 0 1 11 11M3 3a18 18 0 0 1 18 18"
                stroke="currentColor"
                stroke-width="3"
              />
            </svg>
          </span>
        </div>
        <nav aria-label="Rechtliche Informationen">
          <a href="https://stadtplaner.oklabflensburg.de/datenschutz"
            >Datenschutz</a
          ><a href="https://stadtplaner.oklabflensburg.de/impressum"
            >Impressum</a
          ><a
            href="https://github.com/oklabflensburg/open-city-planner-packages/blob/main/LICENSE"
            >Lizenz</a
          >
        </nav>
      </div>
    </div>
  </footer>
</template>
