// Scanner e2e with a fake camera feed. Runs only when PN_E2E_BASE_URL is set.
//
//   cd web && npm run build && npx vite preview --port 4173 &
//   PN_E2E_BASE_URL=http://127.0.0.1:4173 npx playwright test e2e/scan.spec.ts --project=desktop
//
// The backend is mocked with page.route(), so no server is needed. Chromium flags provide a fake
// camera that plays a generated .y4m containing EAN-13 barcodes (see fixtures/barcode-video.ts).
// If Playwright's bundled Chromium is not installed, set PN_CHROMIUM=/path/to/chrome.
import { expect, test, type Page } from '@playwright/test'
import { BARCODE_A, BARCODE_B, writeBarcodeY4m } from './fixtures/barcode-video'

const E2E = !!process.env.PN_E2E_BASE_URL
const y4m = E2E ? writeBarcodeY4m() : ''

test.use({
  permissions: ['camera'],
  serviceWorkers: 'block',
  launchOptions: {
    executablePath: process.env.PN_CHROMIUM || undefined,
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-video-capture=${y4m}`],
  },
})

const PRODUCT = {
  id: 'aaaaaaaa-0000-4000-8000-000000000001', version: 1, name: 'Letmælk', brand: 'Arla', category_id: null,
  default_location_id: null, image_url: null, package_size: 1, package_unit: 'l', stock_unit: 'pcs', min_stock: null,
  ingredients: null, allergens: [], nutrition: null, description: null, countries: [],
  barcodes: [{ code: '0' + BARCODE_A, raw: BARCODE_A, symbology: 'ean_13' }], aliases: [], status: 'known',
  source: 'user', source_attribution: null, lookup_confidence: null, locked_fields: [],
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', deleted_at: null,
}
const SETTINGS = { locale: 'da', allow_negative_stock: false, expiry_soon_days: 3, auto_shopping_low_stock: true, remove_mode_timeout_min: 10, scan_rearm_ms: 600 }

async function mockBackend(page: Page, state: { online: boolean; ops: { client_op_id: string; type: string; barcode?: string; quantity?: number }[] }, kiosk = true) {
  const json = (body: unknown, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) })
  let total = 0
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (!state.online) return route.abort('connectionrefused')
    const p = url.pathname
    if (p === '/api/auth/me')
      return route.fulfill(json({ user: { id: 'u', username: 'kiosk', display_name: 'Kiosk', role: 'member' }, household: { id: 'h', name: 'Hjem' }, kiosk, settings: SETTINGS }))
    if (p === '/api/sync/snapshot')
      return route.fulfill(json({ cursor: '1', products: [PRODUCT], inventory: [{ product_id: PRODUCT.id, total_quantity: total, batches: [] }], locations: [], categories: [], settings: SETTINGS }))
    if (p === '/api/sync/changes') return route.fulfill(json({ cursor: '2', products: [], inventory: [], locations: [], categories: [], full_resync_required: false }))
    if (p === '/api/sync/ops') {
      const body = route.request().postDataJSON() as { ops: { client_op_id: string; type: string; barcode?: string; quantity: number }[] }
      const results = body.ops.map((op) => {
        state.ops.push(op)
        const known = op.barcode === BARCODE_A
        if (known) total += op.type === 'remove' ? -op.quantity : op.quantity
        return { client_op_id: op.client_op_id, status: 'applied', error: null, transaction_id: 't', product: known ? PRODUCT : null, total_quantity: known ? total : null }
      })
      return route.fulfill(json({ results, server_time: new Date().toISOString() }))
    }
    if (p.startsWith('/api/products/by-barcode/')) return route.fulfill(json({ status: 'created_placeholder', product: null, source: null }))
    return route.fulfill(json({}, 404))
  })
}

test.describe('continuous scanner (fake camera)', () => {
  test.skip(!E2E, 'PN_E2E_BASE_URL not set')

  test('hold = one count, re-present = another, unknown does not stop scanning, offline queue syncs', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'camera flags are set up for the desktop project')
    test.setTimeout(90_000)
    const state = { online: true, ops: [] as { client_op_id: string; type: string; barcode?: string }[] }
    await mockBackend(page, state)

    await page.goto('/scan')
    await page.getByTestId('start-scanning').click()
    await expect(page.getByTestId('scan-screen')).toHaveAttribute('data-mode', 'add')

    // The clip loops: A (held 2 s), A again after a gap, B (unknown, held 2 s). Wait for two B's.
    const bIdx = () => state.ops.map((o, i) => (o.barcode === BARCODE_B ? i : -1)).filter((i) => i >= 0)
    // the second (rotated) presentation of A right after the first is NOT counted: it shows the hint instead
    await expect(page.getByTestId('dup-hint')).toBeVisible({ timeout: 30_000 })
    await expect.poll(() => bIdx().length, { timeout: 45_000 }).toBeGreaterThanOrEqual(2)
    await expect(page.getByTestId('last-card')).toBeVisible()
    const [b1, b2] = bIdx()
    // Exactly one loop between the two B's = [A, B]: the held item counts once; the identical item presented again
    // straight after (rotated 45 degrees, same code at any angle) is not counted twice in succession; A after B is.
    expect(state.ops.slice(b1 + 1, b2 + 1).map((o) => o.barcode)).toEqual([BARCODE_A, BARCODE_B])
    expect(state.ops.every((o) => o.type === 'add')).toBe(true)
    expect(new Set(state.ops.map((o) => o.client_op_id)).size).toBe(state.ops.length)

    // Switching to REMOVE is unmistakable and scans become 'remove'
    await page.getByTestId('mode-remove').click()
    await expect(page.getByTestId('scan-screen')).toHaveAttribute('data-mode', 'remove')
    await expect(page.getByTestId('mode-label')).toContainText('FJERN')
    await expect.poll(() => state.ops.some((o) => o.type === 'remove'), { timeout: 40_000 }).toBe(true)
  })

  test('offline: scans are queued and uploaded after reconnect', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'camera flags are set up for the desktop project')
    test.setTimeout(90_000)
    const state = { online: true, ops: [] as { client_op_id: string; type: string; barcode?: string }[] }
    await mockBackend(page, state)
    await page.goto('/scan')
    await page.getByTestId('start-scanning').click()
    await expect.poll(() => state.ops.length, { timeout: 40_000 }).toBeGreaterThanOrEqual(1)
    state.online = false
    const before = state.ops.length
    await expect(page.getByTestId('sync-pill')).toContainText(/Offline|venter/, { timeout: 45_000 })
    state.online = true
    await expect.poll(() => state.ops.length, { timeout: 45_000 }).toBeGreaterThan(before)
    const ids = state.ops.map((o) => o.client_op_id)
    expect(new Set(ids).size).toBe(ids.length) // exactly once
  })
})

test.describe('hand scanner, quantity and sessions', () => {
  test.skip(!E2E, 'PN_E2E_BASE_URL not set')

  test('keyboard-wedge bursts scan, typing does not; +5 is one op; exit shows the session', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop only')
    test.setTimeout(60_000)
    const state = { online: true, ops: [] as { client_op_id: string; type: string; barcode?: string; quantity?: number }[] }
    await mockBackend(page, state, false)
    // station without camera: hand scanner only
    await page.addInitScript(() => localStorage.setItem('pn.scan.prefs', JSON.stringify({ camera: false })))
    await page.goto('/scan')
    await page.getByTestId('start-scanning').click()
    await expect(page.getByTestId('camera-off')).toBeVisible()

    // a person typing digits slowly is not a scan
    await page.keyboard.type('5701234', { delay: 150 })
    await page.keyboard.press('Enter')
    // the scanner types fast and ends with Enter
    await page.keyboard.type(BARCODE_A, { delay: 5 })
    await page.keyboard.press('Enter')
    await expect(page.getByTestId('last-name')).toHaveText('Letmælk')
    // the same item again is not counted (hand scanner follows the same rule): hint, still +1.
    // Wait past the HID trigger-bounce window (350 ms) so this exercises the owner rule, not the bounce filter.
    await page.waitForTimeout(600)
    await page.keyboard.type(BARCODE_A, { delay: 5 })
    await page.keyboard.press('Enter')
    await expect(page.getByTestId('dup-hint')).toBeVisible()
    await expect(page.getByTestId('last-delta')).toHaveText('+1')
    await page.getByTestId('more-5').click()
    await expect(page.getByTestId('last-delta')).toHaveText('+6')
    await expect.poll(() => state.ops.map((o) => [o.barcode, o.quantity]), { timeout: 20_000 }).toEqual([
      [BARCODE_A, 1],
      [BARCODE_A, 5],
    ])

    await page.getByTestId('scan-exit').click()
    const sum = page.getByTestId('session-summary')
    await expect(sum).toContainText('+6')
    await expect(sum).toContainText('Letmælk')
    await page.getByTestId('session-done').click()
    await expect(page.getByTestId('start-scanning')).toBeVisible()
  })
})

test.describe('direct scanner link', () => {
  test.skip(!E2E, 'PN_E2E_BASE_URL not set')

  test('autostart=1&mode=remove starts scanning without a tap and uses the scanner manifest', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop only')
    const state = { online: true, ops: [] as { client_op_id: string; type: string; barcode?: string }[] }
    await mockBackend(page, state)
    await page.goto('/scan?autostart=1&mode=remove')
    await expect(page.getByTestId('scan-screen')).toHaveAttribute('data-mode', 'remove') // no Start tap
    await expect(page.locator('link[rel="manifest"]')).toHaveAttribute('href', '/manifest-scan.webmanifest')
    await expect(page.locator('meta[name="apple-mobile-web-app-title"]')).toHaveAttribute('content', 'Scan')
    const m = await (await page.request.get('/manifest-scan.webmanifest')).json()
    expect(m).toMatchObject({ short_name: 'Scan', start_url: '/scan?autostart=1', scope: '/', display: 'standalone' })
  })

  test('autostart=1&camera=off starts the hand-scanner station; without autostart the Start button shows', async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop', 'desktop only')
    const state = { online: true, ops: [] as { client_op_id: string; type: string; barcode?: string }[] }
    await mockBackend(page, state, false)
    await page.goto('/scan?autostart=1&camera=off')
    await expect(page.getByTestId('camera-off')).toBeVisible()
    await page.goto('/scan?camera=on')
    await expect(page.getByTestId('start-scanning')).toBeVisible()
  })
})
