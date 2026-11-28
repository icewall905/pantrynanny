import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { mockFetch, renderApp } from '../test/utils'

const h = vi.hoisted(() => ({
  enqueueOp: vi.fn(async (op: unknown) => op),
  online: true,
  cacheProduct: vi.fn(async () => {}),
  searchProducts: vi.fn(async () => [] as unknown[]),
}))
vi.mock('../offline', () => ({
  enqueueOp: h.enqueueOp,
  getStore: () => ({
    getLocations: async () => [{ id: 'l1', name: 'Køleskab', icon: null, sort_order: 0, is_default: true, deleted_at: null }],
    cacheProduct: h.cacheProduct,
    searchProducts: h.searchProducts,
  }),
  useSyncStatus: () => ({ online: h.online, pending: 0, syncing: false, lastSyncAt: null, error: null }),
}))

import { ManualAddSheet, parseQty } from './ManualAddSheet'

const product = (id: string, name: string) => ({
  id, version: 1, name, brand: null, category_id: null, default_location_id: null, image_url: null,
  package_size: null, package_unit: null, stock_unit: 'pcs', min_stock: null, ingredients: null, allergens: [], nutrition: null,
  description: null, countries: [], barcodes: [], aliases: [], status: 'known', source: 'user', source_attribution: null,
  lookup_confidence: null, locked_fields: [], created_at: '', updated_at: '', deleted_at: null,
})

beforeEach(() => {
  h.enqueueOp.mockClear()
  h.cacheProduct.mockClear()
  h.searchProducts.mockReset().mockResolvedValue([])
  h.online = true
})

describe('parseQty', () => {
  it('accepts positive numbers with comma or dot, rejects the rest', () => {
    expect(parseQty('2')).toBe(2)
    expect(parseQty('1,5')).toBe(1.5)
    expect(parseQty('0')).toBeNull()
    expect(parseQty('-1')).toBeNull()
    expect(parseQty('abc')).toBeNull()
  })
})

describe('ManualAddSheet', () => {
  it('adds an existing product with quantity, location and expiry through enqueueOp', async () => {
    const calls = mockFetch({ 'GET /products': [product('p1', 'Æbler')] })
    const onAdded = vi.fn()
    const user = userEvent.setup()
    renderApp(<ManualAddSheet open onClose={() => {}} onAdded={onAdded} />)
    await user.type(screen.getByTestId('manual-add-name'), 'æb')
    await user.click(await screen.findByRole('option', { name: /Æbler/ }))
    expect(calls.some((c) => c.method === 'GET' && c.path === '/products')).toBe(true)
    await user.clear(screen.getByTestId('manual-add-qty'))
    await user.type(screen.getByTestId('manual-add-qty'), '3')
    await user.selectOptions(await screen.findByTestId('manual-add-location'), 'l1')
    await user.type(screen.getByTestId('manual-add-expiry'), '2030-01-31')
    await user.click(screen.getByTestId('manual-add-submit'))
    await waitFor(() =>
      expect(h.enqueueOp).toHaveBeenCalledWith({ type: 'add', product_id: 'p1', quantity: 3, location_id: 'l1', expires_at: '2030-01-31' }),
    )
    expect(onAdded).toHaveBeenCalledWith(expect.objectContaining({ id: 'p1' }), 3)
  })

  it('creates a product without barcode, then adds it with automatic location', async () => {
    const calls = mockFetch({ 'GET /products': [], 'POST /products': product('p2', 'Rabarber') })
    const user = userEvent.setup()
    renderApp(<ManualAddSheet open onClose={() => {}} />)
    await user.type(screen.getByTestId('manual-add-name'), 'Rabarber')
    await user.click(await screen.findByTestId('manual-add-create'))
    expect(await screen.findByTestId('manual-add-product')).toHaveTextContent('Rabarber')
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'Rabarber' })
    expect(h.cacheProduct).toHaveBeenCalled()
    await user.click(screen.getByTestId('manual-add-submit'))
    await waitFor(() =>
      expect(h.enqueueOp).toHaveBeenCalledWith({ type: 'add', product_id: 'p2', quantity: 1, location_id: null, expires_at: null }),
    )
  })

  it('offline: finds cached products, but creating needs a connection', async () => {
    h.online = false
    h.searchProducts.mockResolvedValue([product('p3', 'Ris')])
    const fetchFn = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    vi.stubGlobal('fetch', fetchFn)
    const user = userEvent.setup()
    renderApp(<ManualAddSheet open onClose={() => {}} />)
    await user.type(screen.getByTestId('manual-add-name'), 'ri')
    expect(await screen.findByRole('option', { name: /Ris/ })).toBeInTheDocument()
    await user.click(screen.getByTestId('manual-add-create'))
    expect(await screen.findByRole('alert')).toHaveTextContent(/forbindelse/)
    expect(fetchFn.mock.calls.some((c) => (c as unknown[])[1] && ((c as unknown[])[1] as RequestInit).method === 'POST')).toBe(false)
  })
})
