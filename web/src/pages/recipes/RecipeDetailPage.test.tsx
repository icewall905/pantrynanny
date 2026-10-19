import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { mockFetch, renderApp, ME } from '../../test/utils'
import { AuthProvider } from '../../auth/AuthProvider'

let n = 0
const enqueueOp = vi.fn(async (op: Record<string, unknown>) => ({ ...op, client_op_id: `op-${++n}` }))
vi.mock('../../offline', () => ({ enqueueOp: (op: Record<string, unknown>) => enqueueOp(op) }))

import RecipeDetailPage from './RecipeDetailPage'

const ing = (i: number, raw: string, name: string) => ({ id: `i${i}`, position: i, raw, name, quantity: null, unit: null, note: null, optional: false, product_id: null })
const RECIPE = {
  id: 'r1', version: 1, title: 'Pandekager', description: null, servings: 4, prep_min: 10, cook_min: 20, instructions: ['Pisk'],
  tags: [], source_url: null, source_name: null, image_url: null, created_at: '', updated_at: '',
  ingredients: [ing(0, '3 æg', 'æg'), ing(1, '5 dl mælk', 'mælk'), ing(2, '250 g mel', 'mel'), ing(3, 'smør', 'smør')],
}
const P = (id: string, name: string, q: number) => ({ id, name, total_quantity: q, stock_unit: 'pcs', image_url: null, next_expiry: null })
const AVAIL = {
  recipe_id: 'r1', servings: 4, have: 3, missing: 1, required: 4, coverage: 0.75, uses_expiring: [],
  items: [
    { ingredient: RECIPE.ingredients[0], status: 'have', product: P('egg', 'Æg', 10), linked: false, need: 3, enough: true, expiring: false },
    { ingredient: RECIPE.ingredients[1], status: 'have', product: P('milk', 'Letmælk', 1), linked: false, need: 0.5, enough: true, expiring: false },
    { ingredient: RECIPE.ingredients[2], status: 'missing', product: null, linked: false, need: null, enough: null, expiring: false },
    { ingredient: RECIPE.ingredients[3], status: 'have', product: P('butter', 'Smør', 1), linked: false, need: null, enough: null, expiring: false },
  ],
}

beforeEach(() => {
  enqueueOp.mockClear()
  mockFetch({ 'GET /auth/me': ME, 'GET /recipes/r1': RECIPE, 'GET /recipes/r1/availability': AVAIL })
})

const render = () =>
  renderApp(
    <AuthProvider>
      <Routes>
        <Route path="/recipes/:id" element={<RecipeDetailPage />} />
      </Routes>
    </AuthProvider>,
    '/recipes/r1',
  )

describe('Cook this', () => {
  it('shows the amounts, deducts only after confirming, and can be undone', async () => {
    render()
    await userEvent.click(await screen.findByTestId('cook-open'))
    const lines = await screen.findByTestId('cook-lines')
    // unknown amount (butter) is not ticked by default; nothing has been deducted yet
    expect(within(lines).getByRole('checkbox', { name: 'Smør' })).not.toBeChecked()
    expect(enqueueOp).not.toHaveBeenCalled()
    await userEvent.click(within(lines).getByRole('checkbox', { name: 'Letmælk' })) // keep the milk
    await userEvent.click(screen.getByTestId('cook-confirm'))
    await waitFor(() => expect(enqueueOp).toHaveBeenCalledTimes(1))
    expect(enqueueOp).toHaveBeenCalledWith({ type: 'remove', product_id: 'egg', quantity: 3, reason: 'recipe' })
    await userEvent.click(await screen.findByRole('button', { name: /Fortryd/ }))
    await waitFor(() =>
      expect(enqueueOp).toHaveBeenLastCalledWith({ type: 'undo', undoes_client_op_id: 'op-1', product_id: 'egg', quantity: 3 }),
    )
  })
})
