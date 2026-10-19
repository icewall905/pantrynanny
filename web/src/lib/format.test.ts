import { describe, expect, it } from 'vitest'
import type { Category, ShoppingItem } from '../api/types'
import { expiryState, groupShopping, shoppingToText } from './format'

const now = new Date(2026, 9, 19, 12)
const cat = (id: string, name: string, sort_order: number): Category => ({ id, name, icon: null, color: null, sort_order, deleted_at: null })
const item = (p: Partial<ShoppingItem>): ShoppingItem => ({
  id: Math.random().toString(),
  version: 1,
  product_id: null,
  name: 'x',
  quantity: 1,
  unit: null,
  category_id: null,
  note: null,
  checked: false,
  checked_at: null,
  source: 'manual',
  created_at: '',
  updated_at: '',
  ...p,
})

describe('expiryState', () => {
  it('classifies dates', () => {
    expect(expiryState('2026-10-18', 3, now)).toBe('expired')
    expect(expiryState('2026-10-19', 3, now)).toBe('soon')
    expect(expiryState('2026-10-22', 3, now)).toBe('soon')
    expect(expiryState('2026-10-23', 3, now)).toBe('ok')
    expect(expiryState(null, 3, now)).toBe('none')
  })
})

describe('shopping grouping', () => {
  const cats = [cat('b', 'Mejeri', 2), cat('a', 'Frugt', 1)]
  const items = [
    item({ name: 'Mælk', category_id: 'b', quantity: 2, unit: 'l' }),
    item({ name: 'Æbler', category_id: 'a', quantity: 6 }),
    item({ name: 'Batterier' }),
    item({ name: 'Smør', category_id: 'b', checked: true }),
  ]
  it('orders groups by category, uncategorised last, checked last in group', () => {
    const g = groupShopping(items, cats)
    expect(g.map((x) => x.category?.name ?? null)).toEqual(['Frugt', 'Mejeri', null])
    expect(g[1].items.map((i) => i.name)).toEqual(['Mælk', 'Smør'])
  })
  it('creates plain text with open items only', () => {
    expect(shoppingToText(items, cats, 'Andet')).toBe('Frugt:\n- 6 x Æbler\n\nMejeri:\n- 2 l Mælk\n\nAndet:\n- Batterier')
  })
})
