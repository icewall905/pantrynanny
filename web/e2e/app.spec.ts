import { expect, test } from '@playwright/test'
import { login, requireBackend } from './helpers'

test.beforeEach(async ({ page }) => {
  requireBackend()
  await login(page)
})

test('create a product manually and adjust its stock', async ({ page }) => {
  const name = `E2E Mælk ${Date.now()}`
  await page.goto('/products/new')
  await page.getByLabel('Navn', { exact: true }).fill(name)
  await page.getByRole('button', { name: 'Gem' }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await page.getByRole('button', { name: new RegExp(`Tilføj én ${name}`) }).click()
  await expect(page.getByText('Tilføjet').first()).toBeVisible({ timeout: 10_000 })
})

test('inventory search and navigation tabs work', async ({ page }) => {
  await page.goto('/inventory')
  await page.getByRole('searchbox').fill('mælk')
  await expect(page.getByRole('searchbox')).toHaveValue('mælk')
  for (const path of ['/shopping', '/expiring', '/unknown', '/stats', '/export', '/settings']) {
    await page.goto(path)
    await expect(page.locator('h1')).toBeVisible()
  }
})

test('shopping list: add free text item and check it off', async ({ page }) => {
  const item = `E2E vare ${Date.now()}`
  await page.goto('/shopping')
  await page.getByPlaceholder('Tilføj vare…').fill(item)
  await page.getByRole('button', { name: 'Tilføj', exact: true }).click()
  await expect(page.getByText(item)).toBeVisible()
  await page.getByRole('checkbox', { name: `Afkryds ${item}` }).click()
  await expect(page.getByRole('checkbox', { name: `Afkryds ${item}` })).toHaveAttribute('aria-checked', 'true')
  await page.getByRole('button', { name: /Fjern afkrydsede/ }).click()
})

test('language can be switched to English', async ({ page }) => {
  await page.goto('/settings')
  await page.getByRole('button', { name: 'English' }).click()
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await page.getByRole('button', { name: 'Dansk' }).click()
})
