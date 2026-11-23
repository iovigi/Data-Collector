import { expect, test } from "@playwright/test";

const EMAIL = process.env.E2E_USER_EMAIL || "e2e.admin@example.com";
const PASSWORD = process.env.E2E_USER_PASSWORD || "StrongE2EPassword123!";

test("login -> onboarding -> project -> collection -> record -> logout", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await page.waitForURL(/\/(onboarding\/create-workspace|w\/)/);
  if (page.url().includes("/onboarding/create-workspace")) {
    await page.getByLabel("Workspace name").fill("E2E Workspace");
    await page.getByLabel("Workspace slug (3–64 lowercase chars)").fill(`e2e-ws-${Date.now()}`);
    await page.getByRole("button", { name: "Create workspace & continue" }).click();
    await page.waitForURL(/\/w\/.*\/overview/);
  }

  await expect(page.getByRole("heading", { name: "Workspace Overview" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(/\/login/);
});
