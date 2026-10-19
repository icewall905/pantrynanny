import { expect, test } from '@playwright/test'
import { login, requireBackend } from './helpers'

test.beforeEach(requireBackend)

test('unauthenticated visitors are sent to the login page', async ({ page }) => {
  await page.goto('/inventory')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('button', { name: 'Log ind' })).toBeVisible()
})

test('login shows the dashboard with a scan button', async ({ page }) => {
  await login(page)
  await expect(page.getByRole('link', { name: 'Scan varer' }).first()).toBeVisible()
})

test('wrong password shows an error', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Brugernavn').fill('nobody')
  await page.getByLabel('Adgangskode').fill('wrong-password')
  await page.getByRole('button', { name: 'Log ind' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
})
