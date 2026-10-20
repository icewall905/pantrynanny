import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { mockFetch, renderApp } from '../test/utils'
const enqueueOp = vi.fn(async (op: Record<string, unknown>) => ({ ...op, client_op_id: 'x' }))
vi.mock('../offline', () => ({ enqueueOp: (op: Record<string, unknown>) => enqueueOp(op) }))

import ShoppingPage from './ShoppingPage'

const base = { version: 1, product_id: null, unit: null, note: null, checked_at: null, source: 'manual', created_at: '', updated_at: '' }

let calls: ReturnType<typeof mockFetch>
beforeEach(() => {
  calls = mockFetch({
    'PATCH /shopping/s1': { ...base, id: 's1', name: 'Mælk', quantity: 3, category_id: 'c1', checked: false },
    'GET /categories': [{ id: 'c1', name: 'Mejeri', icon: null, color: null, sort_order: 1, deleted_at: null }],
    'GET /shopping': [
      { ...base, id: 's1', name: 'Mælk', quantity: 2, category_id: 'c1', checked: false },
      { ...base, id: 's2', name: 'Batterier', quantity: 1, category_id: null, checked: false },
      { ...base, id: 's3', name: 'Smør', quantity: 2, category_id: 'c1', checked: true, product_id: 'p-smor', unit: 'pcs', store: 'Netto' },
    ],
    'GET /shopping/suggestions': [],
    'POST /shopping/clear-checked': { removed: 1 },
  })
})

describe('ShoppingPage', () => {
  it('groups by category and copies the open items as plain text', async () => {
    const user = userEvent.setup()
    const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    renderApp(<ShoppingPage />)
    expect(await screen.findByRole('heading', { name: 'Mejeri' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Andet' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Fjern afkrydsede \(1\)/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Kopiér liste/ }))
    await waitFor(() => expect(write).toHaveBeenCalledWith('Mejeri:\n- 2 x Mælk\n\nAndet:\n- Batterier'))
  })

  it('omits If-Match when only toggling checked, keeps it for quantity edits', async () => {
    const user = userEvent.setup()
    renderApp(<ShoppingPage />)
    await user.click(await screen.findByRole('checkbox', { name: 'Afkryds Mælk' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')!.headers['If-Match']).toBeUndefined()
    await user.click(screen.getByRole('button', { name: 'Flere Mælk' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'PATCH').length).toBe(2))
    expect(calls.filter((c) => c.method === 'PATCH')[1].headers['If-Match']).toBe('1')
  })

  it('puts ticked items into stock after confirming, then clears them', async () => {
    const user = userEvent.setup()
    renderApp(<ShoppingPage />)
    await user.click(await screen.findByTestId('put-away'))
    expect(enqueueOp).not.toHaveBeenCalled()
    await user.click(screen.getByTestId('put-away-confirm'))
    await waitFor(() => expect(enqueueOp).toHaveBeenCalledWith({ type: 'add', product_id: 'p-smor', quantity: 2 }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/shopping/clear-checked')).toBe(true))
  })

  it('can group by shop', async () => {
    const user = userEvent.setup()
    renderApp(<ShoppingPage />)
    await user.click(await screen.findByRole('button', { name: /Butik/ }))
    expect(screen.getByRole('heading', { name: 'Netto' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Alle butikker' })).toBeInTheDocument()
  })
})
