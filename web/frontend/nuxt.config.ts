import tailwindcss from '@tailwindcss/vite'

export default defineNuxtConfig({
  ssr: true,
  compatibilityDate: '2026-08-30',
  css: ['~/assets/css/main.css'],
  devtools: { enabled: false },
  modules: [],
  runtimeConfig: {
    apiBaseInternal: process.env.NUXT_API_BASE_INTERNAL || 'http://127.0.0.1:8000/api',
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8000/api',
      siteUrl: process.env.NUXT_PUBLIC_SITE_URL || 'https://packages.stadtplaner.oklabflensburg.de',
    },
  },
  typescript: { strict: true, typeCheck: true },
  vite: { plugins: [tailwindcss()] },
})
