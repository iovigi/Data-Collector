import { defineConfig } from "@playwright/test";

// PLAYWRIGHT_BASE_URL: the deployed site, e.g. https://data.devart.solutions
// PLAYWRIGHT_HOST_RESOLVER: optional Chromium rule, e.g. "MAP data.devart.solutions 104.21.80.234"
// (bypasses a hosts-file entry that points the hostname at 127.0.0.1 on the server itself)
const resolver = process.env.PLAYWRIGHT_HOST_RESOLVER;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    launchOptions: resolver ? { args: [`--host-resolver-rules=${resolver}`] } : undefined,
  },
});
