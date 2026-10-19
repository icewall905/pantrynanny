import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { mockFetch, renderApp, ME } from '../test/utils'
import { AuthProvider } from '../auth/AuthProvider'

const enqueueOp = vi.fn(async (op: Record<string, unknown>) => ({ ...op, client_op_id: 'op-1' }))
vi.mock('../offline', () => ({
  enqueueOp: (op: Record<string, unknown>) => enqueueOp(op),
  getStore: () => ({ subscribeData: () => () => undefined }),
}))

import KitchenPage from './KitchenPage'

const product = (id: string, name: string, favorite = false) => ({
  id, name, favorite, version: 1, brand: null, category_id: null, default_location_id: null, image_url: null,
  package_size: null, package_unit: null, stock_unit: 'pcs', min_stock: null, ingredients: null, allergens: [],
  nutrition: null, description: null, countries: [], barcodes: [], aliases: [], status: 'known', source: 'user',
  source_attribution: null, lookup_confidence: null, locked_fields: [], created_at: '', updated_at: '', deleted_at: null,
})
const tile = (p: ReturnType<typeof product>, qty: number) => ({ product: p, total_quantity: qty, batches: [], next_expiry: null, low_stock: false, uses: 3 })

beforeEach(() => {
  enqueueOp.mockClear()
  mockFetch({
    'GET /auth/me': ME,
    'GET /dashboard': {
      totals: { products_in_stock: 1, items: 2 }, low_stock: [], expiring_soon: [], expired: [], recently_added: [],
      recently_consumed: [], unknown_count: 0, shopping_open_count: 4, by_location: [],
    },
    'GET /kitchen/tiles': [tile(product('p1', 'Mælk', true), 2), tile(product('p2', 'Smør'), 0)],
  })
})

describe('KitchenPage', () => {
  it('one tap takes one, undo puts it back', async () => {
    renderApp(
      <AuthProvider>
        <Routes>
          <Route path="*" element={<KitchenPage />} />
        </Routes>
      </AuthProvider>,
    )
    const milk = await screen.findByRole('button', { name: /Mælk/ })
    expect(screen.getByRole('button', { name: /Smør/ })).toBeDisabled() // nothing left to take
    await userEvent.click(milk)
    await waitFor(() => expect(enqueueOp).toHaveBeenCalledWith({ type: 'remove', product_id: 'p1', quantity: 1 }))
    expect(within(milk).getByTestId('kitchen-qty')).toHaveTextContent(/^1/)
    await userEvent.click(screen.getByTestId('kitchen-undo'))
    await waitFor(() =>
      expect(enqueueOp).toHaveBeenLastCalledWith({ type: 'undo', undoes_client_op_id: 'op-1', product_id: 'p1', quantity: 1 }),
    )
    expect(within(milk).getByTestId('kitchen-qty')).toHaveTextContent(/^2/)
  })
})
