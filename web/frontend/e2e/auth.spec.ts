import { test, expect } from "@playwright/test";

test("local account, SSR refresh, logout/login and real WebAuthn", async ({
  page,
  context,
}) => {
  const email = `e2e-${Date.now()}@example.org`;
  const password = "NOT_A_SECRET_E2E_TEST_SENTINEL";
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/registrieren");
  await page.getByLabel("E-Mail", { exact: true }).fill(email);
  await page.getByLabel("Passwort", { exact: true }).fill(password);
  await page.getByLabel("Passwort bestätigen", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Registrieren", exact: true }).click();
  await expect(page).toHaveURL(/\/profil$/);
  await expect(
    page.getByRole("heading", { name: "Profil", exact: true, level: 1 }),
  ).toBeVisible();
  const me = await context.request.get("/api/v1/auth/me");
  expect(me.ok()).toBeTruthy();
  expect((await me.json()).email).toBe(email);
  let cookies = await context.cookies();
  const access = cookies.find((c) => c.name === "ocp_hub_access_token")!;
  const refresh = cookies.find((c) => c.name === "ocp_hub_refresh_token")!;
  expect(access.httpOnly && refresh.httpOnly).toBeTruthy();
  expect(refresh.path).toBe("/");
  const csrf = cookies.find((c) => c.name === "ocp_hub_csrf_token")!;
  const htmlResponse = await context.request.get("/profil");
  expect(htmlResponse.headers()["cache-control"]).toContain("no-store");
  const html = await htmlResponse.text();
  expect(html).toContain(email);
  expect(html).toMatch(/name="robots" content="noindex, nofollow"/);
  for (const value of [access.value, refresh.value, csrf.value])
    expect(html).not.toContain(value);
  const home = await context.request.get("/");
  expect(home.ok()).toBeTruthy();
  expect(home.headers()["cache-control"]).toContain("no-store");
  // Simulate an expired access cookie while retaining the real database refresh session.
  await context.clearCookies({ name: "ocp_hub_access_token" });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Profil", exact: true, level: 1 }),
  ).toBeVisible();
  cookies = await context.cookies();
  expect(
    cookies.find((c) => c.name === "ocp_hub_refresh_token")?.value,
  ).not.toBe(refresh.value);
  await page.getByRole("button", { name: "Abmelden", exact: true }).click();
  await page.goto("/anmelden");
  expect((await context.request.get("/api/v1/auth/me")).status()).toBe(401);
  await page.getByLabel("E-Mail", { exact: true }).fill(email);
  await page.getByLabel("Passwort", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/\/profil$/);
  await page.screenshot({
    path: "test-results/auth-profile.png",
    fullPage: true,
  });
  // Chromium virtual authenticator exercises actual signed ceremonies and backend verification.
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
  await page
    .getByRole("button", { name: "Passkey hinzufügen", exact: true })
    .click();
  await page.getByLabel("Name des neuen Passkeys").fill("E2E Passkey");
  await page
    .getByRole("button", { name: "Passkey hinzufügen", exact: true })
    .click();
  await expect(
    page.getByText("Passkey hinzugefügt.", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Mit Passkey erneut bestätigen" })
    .click();
  await expect(
    page.getByText("Anmeldung erneut bestätigt.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Abmelden", exact: true }).click();
  await page.goto("/anmelden");
  await page
    .getByRole("button", { name: "Mit Passkey anmelden", exact: true })
    .click();
  await expect(page).toHaveURL(/\/profil$/);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => Object.keys(localStorage))).not.toContain(
    "token",
  );
});

test("email bearer tokens are absent from server-rendered HTML", async ({
  request,
}) => {
  const token = "NOT_A_SECRET_EMAIL_TOKEN_SENTINEL";
  for (const path of ["email-bestaetigen", "passwort-zuruecksetzen"]) {
    const response = await request.get(`/${path}?token=${token}`);
    expect(response.headers()["cache-control"]).toContain("no-store");
    expect(await response.text()).not.toContain(token);
  }
});

test("browser consumes an email token without keeping it in URL or HTML", async ({
  page,
}) => {
  const token = "NOT_A_SECRET_EMAIL_TOKEN_SENTINEL";
  let submitted = "";
  await page.route("**/api/v1/auth/verify-email", async (route) => {
    submitted = route.request().postDataJSON().token;
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          error: { code: "INVALID_TOKEN", message: "Test-Link ist ungültig." },
        },
      }),
    });
  });
  await page.goto(`/email-bestaetigen?token=${token}`);
  await expect(page).toHaveURL(/\/email-bestaetigen$/);
  expect(await page.content()).not.toContain(token);
  await page
    .getByRole("button", { name: "E-Mail bestätigen", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Test-Link ist ungültig.",
  );
  expect(submitted).toBe(token);
});
