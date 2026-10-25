import { describe, expect, it } from 'vitest'
import type { InventoryItem, StockBatch } from '../api/types'
import { chunk, fixUpRows } from './fixUp'

const batch = (id: string, location_id: string, expires_at: string | null, quantity = 1): StockBatch => ({
  id, product_id: 'p', location_id, quantity, expires_at, opened_at: null, created_at: '', updated_at: '',
})
const item = (name: string, batches: StockBatch[]) =>
  ({ product: { id: name, name, brand: null }, batches, total_quantity: 0, next_expiry: null, low_stock: false }) as unknown as InventoryItem

const items = [
  item('Mælk', [batch('m1', 'fridge', null), batch('m2', 'fridge', '2026-11-01'), batch('m0', 'fridge', null, 0)]),
  item('Ærter', [batch('a1', 'freezer', null)]),
  item('Kaffe', [batch('k1', 'pantry', '2027-01-01')]),
]

describe('fixUpRows', () => {
  it('lists every batch in stock, sorted by name', () => {
    expect(fixUpRows(items).map((r) => r.batch.id)).toEqual(['k1', 'm1', 'm2', 'a1'])
  })
  it('filters on missing expiry, location and text', () => {
    expect(fixUpRows(items, { noExpiry: true }).map((r) => r.batch.id)).toEqual(['m1', 'a1'])
    expect(fixUpRows(items, { locationId: 'fridge' }).map((r) => r.batch.id)).toEqual(['m1', 'm2'])
    expect(fixUpRows(items, { noExpiry: true, locationId: 'fridge' }).map((r) => r.batch.id)).toEqual(['m1'])
    expect(fixUpRows(items, { q: 'kaf' }).map((r) => r.batch.id)).toEqual(['k1'])
  })
})

describe('chunk', () => {
  it('splits into request-sized pieces', () => {
    expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]])
    expect(chunk([], 2)).toEqual([])
  })
})
