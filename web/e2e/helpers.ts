import { expect, test, type Page } from '@playwright/test'

export const E2E = !!process.env.PN_E2E_BASE_URL
export const USER = process.env.PN_E2E_USER ?? 'admin'
export const PASSWORD = process.env.PN_E2E_PASSWORD ?? 'admin'

export function requireBackend() {
  test.skip(!E2E, 'PN_E2E_BASE_URL not set – e2e needs a running backend')
}

export async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Brugernavn').fill(USER)
  await page.getByLabel('Adgangskode').fill(PASSWORD)
  await page.getByRole('button', { name: 'Log ind' }).click()
  await expect(page).not.toHaveURL(/\/login/)
}
