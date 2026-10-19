import { expect, test } from '@playwright/test'
import { login, requireBackend } from './helpers'

test.beforeEach(async ({ page }) => {
  requireBackend()
  await login(page)
})

test('write a recipe, see what is missing, plan it, and put the missing item on the list', async ({ page }) => {
  const title = `E2E Grød ${Date.now()}`
  await page.goto('/recipes/new')
  await page.getByLabel('Titel').fill(title)
  await page.getByLabel('Ingredienser').fill('2 dl havregryn\n4 dl vand\nevt. rosiner')
  await expect(page.getByTestId('parse-preview')).toContainText('havregryn')
  await page.getByTestId('recipe-save').click()
  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  const ingredients = page.getByTestId('ingredients')
  await expect(ingredients).toContainText('mangler') // havregryn
  await expect(ingredients).toContainText('basis') // water is assumed
  await expect(ingredients).toContainText('valgfri')

  await page.getByRole('button', { name: /manglende på listen/ }).click()
  // added now, or already on the list from an earlier run: never twice
  await expect(page.getByText(/sat på indkøbslisten|Intet at købe/)).toBeVisible()

  await page.getByRole('button', { name: 'Planlæg' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Gem' }).click()
  await page.goto('/plan')
  await expect(page.getByTestId('plan-week')).toContainText(title)

  await page.goto('/shopping')
  await expect(page.getByText('havregryn', { exact: true })).toHaveCount(1) // never added twice
  await page.goto('/recipes')
  await expect(page.getByTestId('recipe-list')).toContainText(title)
})

test('kitchen screen and activity timeline load', async ({ page }) => {
  await page.goto('/kitchen')
  await expect(page.getByTestId('kitchen')).toBeVisible()
  await expect(page.getByTestId('kitchen-scan-in')).toBeVisible()
  await page.goto('/activity')
  await expect(page.locator('h1')).toHaveText('Aktivitet')
})
