import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  retries: 0,
  timeout: 60000,
  use: {
    baseURL: process.env.AUTH_E2E_BASE_URL,
    browserName: "chromium",
    trace: "off",
  },
});
