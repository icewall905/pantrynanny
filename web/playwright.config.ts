import { defineConfig, devices } from '@playwright/test'

// E2E runs against a real, seeded backend. Set PN_E2E_BASE_URL (e.g. http://127.0.0.1:8734),
// plus PN_E2E_USER / PN_E2E_PASSWORD for a login. Without PN_E2E_BASE_URL the specs are skipped.
// PN_CHROMIUM points at a preinstalled Chromium when the bundled browser version is unavailable.
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.PN_E2E_BASE_URL ?? 'http://127.0.0.1:8734',
    trace: 'retain-on-failure',
    locale: 'da-DK',
    launchOptions: { executablePath: process.env.PN_CHROMIUM || undefined },
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', use: { ...devices['Pixel 7'] } },
  ],
})
