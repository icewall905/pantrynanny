import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { mockFetch, renderApp, ME } from '../test/utils'
import { AuthProvider } from '../auth/AuthProvider'

const enqueueOp = vi.hoisted(() => vi.fn(async (op: unknown) => op))
vi.mock('../offline', () => ({
  enqueueOp,
  syncNow: async () => {},
  useSyncStatus: () => ({ online: true, pending: 0, syncing: false, lastSyncAt: null, error: null }),
}))

import InventoryPage from './InventoryPage'

const product = {
  id: 'p1', version: 1, name: 'Letmælk', brand: 'Arla', category_id: null, default_location_id: null, image_url: null,
  package_size: 1, package_unit: 'l', stock_unit: 'pcs', min_stock: null, ingredients: null, allergens: [], nutrition: null,
  description: null, countries: [], barcodes: [], aliases: [], status: 'known', source: 'user', source_attribution: null,
  lookup_confidence: null, locked_fields: [], created_at: '', updated_at: '', deleted_at: null,
}

beforeEach(() => {
  enqueueOp.mockClear()
  mockFetch({
    'GET /auth/me': ME,
    'GET /locations': [{ id: 'l1', name: 'Køleskab', icon: null, sort_order: 0, is_default: true, deleted_at: null }],
    'GET /categories': [],
    'GET /inventory': [{ product, total_quantity: 2, batches: [], next_expiry: '2000-01-01', low_stock: false }],
  })
})

describe('InventoryPage', () => {
  it('+/- go through enqueueOp and update optimistically', async () => {
    const user = userEvent.setup()
    renderApp(
      <AuthProvider>
        <Routes>
          <Route path="/" element={<InventoryPage />} />
        </Routes>
      </AuthProvider>,
    )
    await screen.findByText('Letmælk')
    expect(screen.getByText('Udløbet')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Tilføj én Letmælk/ }))
    await waitFor(() => expect(enqueueOp).toHaveBeenCalledWith(expect.objectContaining({ type: 'add', product_id: 'p1', quantity: 1 })))
    await user.click(screen.getByRole('button', { name: /Fjern én Letmælk/ }))
    await waitFor(() => expect(enqueueOp).toHaveBeenCalledWith(expect.objectContaining({ type: 'remove', product_id: 'p1', quantity: 1 })))
  })
})
