import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("login page has zero serious or critical axe violations", async ({ page }) => {
  await page.goto("/login");
  const results = await new AxeBuilder({ page }).analyze();
  const severe = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical"
  );
  expect(severe).toEqual([]);
});
