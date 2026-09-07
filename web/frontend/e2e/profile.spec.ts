import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

test("profile layout with provider fixtures at desktop, tablet and mobile widths", async ({
  page,
  context,
}) => {
  await page.goto("/registrieren");
  await page.getByLabel("E-Mail", { exact: true }).fill("mara@example.org");
  await page
    .getByLabel("Passwort", { exact: true })
    .fill("NOT_A_SECRET_PROFILE_TEST");
  await page
    .getByLabel("Passwort bestätigen")
    .fill("NOT_A_SECRET_PROFILE_TEST");
  await page.getByRole("button", { name: "Registrieren", exact: true }).click();
  await expect(page).toHaveURL(/\/profil$/);
  await page.getByLabel("Anzeigename").fill("Mara Hansen");
  await page
    .getByRole("button", { name: "Profil speichern", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Profil gespeichert");
  // Synthetic provider presentation only; local login, session and profile API are real.
  await page.route("**/api/v1/auth/providers", (route) =>
    route.fulfill({ json: { providers: ["github", "google"] } }),
  );
  await page.route("**/api/v1/users/me/oauth-accounts", (route) =>
    route.fulfill({
      json: [
        {
          id: "fixture-github",
          provider: "github",
          provider_username: "mara.codes",
          provider_email: "mara@example.org",
          provider_avatar_url: "https://avatars.example.org/profile-demo.svg",
          provider_profile_url: "https://github.com/example",
          last_login_at: "2026-09-07T08:00:00Z",
        },
      ],
    }),
  );
  await page.route("https://avatars.example.org/profile-demo.svg", (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80"><rect width="80" height="80" fill="#e9f3ff"/><circle cx="40" cy="28" r="14" fill="#6082ad"/><path d="M12 80v-9a28 28 0 0 1 56 0v9" fill="#25466e"/></svg>',
    }),
  );
  await page.reload();
  await expect(page.getByText("mara.codes", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Google-Konto verknüpfen" }),
  ).toBeVisible();
  await expect(page.getByText("Mastodon")).toHaveCount(0);
  const response = await context.request.get("/profil");
  expect(response.headers()["cache-control"]).toContain("no-store");
  const html = await response.text();
  expect(html).toMatch(/name="robots" content="noindex, nofollow"/);
  for (const cookie of await context.cookies()) {
    if (cookie.name.startsWith("ocp_hub_"))
      expect(html).not.toContain(cookie.value);
  }
  const directory = process.env.PROFILE_SCREENSHOT_DIR || "test-results";
  await mkdir(directory, { recursive: true });
  for (const [name, width] of [
    ["desktop", 1440],
    ["tablet", 768],
    ["mobile", 390],
  ] as const) {
    await page.setViewportSize({ width, height: 1000 });
    await page.evaluate(() => document.fonts.ready);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
    // Every card follows the previous one vertically, also on desktop.
    const boxes = await page.locator(".auth-security > section").all();
    let bottom = 0;
    for (const card of boxes) {
      const box = (await card.boundingBox())!;
      expect(box.y).toBeGreaterThanOrEqual(bottom);
      bottom = box.y + box.height;
    }
    await page.screenshot({
      path: resolve(directory, `profile-${name}.png`),
      fullPage: true,
    });
  }
});
