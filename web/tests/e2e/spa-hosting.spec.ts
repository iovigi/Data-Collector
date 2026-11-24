import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const EMAIL = process.env.E2E_USER_EMAIL || "e2e.admin@example.com";
const PASSWORD = process.env.E2E_USER_PASSWORD || "StrongE2EPassword123!";

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/(onboarding\/create-workspace|w\/)/);
}

test("logged-out deep link redirects to login with return path", async ({ page }) => {
  await page.goto("/w/000000000000000000000000/jobs");
  await page.waitForURL(/\/login\?next=/);
  expect(decodeURIComponent(page.url())).toContain("next=/w/000000000000000000000000/jobs");
});

test("deep-link refresh keeps the session and the page (served by IIS)", async ({ page, context }) => {
  await signIn(page);
  test.skip(!page.url().includes("/w/"), "account has no workspace");
  const wid = page.url().match(/\/w\/([a-f0-9]{24})/)![1];
  await page.goto(`/w/${wid}/collections`);
  await page.reload();
  await expect(page).toHaveURL(new RegExp(`/w/${wid}/collections`));
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  const cookies = await context.cookies();
  const sid = cookies.find((c) => c.name === "__Host-dc_sid");
  expect(sid?.httpOnly).toBe(true);
  expect(sid?.secure).toBe(true);
  expect(await page.evaluate(() => document.cookie)).not.toContain("dc_sid");
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(/\/login/);
});

test.describe("mobile viewport", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("login usable and accessible on a phone", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(390);
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
});
