// Bulk "fix up stock": one row per in-stock batch, filtered. Pure so it can be tested.
import type { InventoryItem, Product, StockBatch } from '../api/types'

export interface FixUpRow {
  batch: StockBatch
  product: Product
}

export interface FixUpFilter {
  /** only batches without an expiry date */
  noExpiry?: boolean
  /** only batches in this location ('' / undefined = all) */
  locationId?: string
  /** case-insensitive name/brand search */
  q?: string
}

export function fixUpRows(items: InventoryItem[], f: FixUpFilter = {}): FixUpRow[] {
  const q = f.q?.trim().toLocaleLowerCase()
  const out: FixUpRow[] = []
  for (const it of items) {
    if (q && !`${it.product.name} ${it.product.brand ?? ''}`.toLocaleLowerCase().includes(q)) continue
    for (const b of it.batches) {
      if (!(b.quantity > 0)) continue
      if (f.noExpiry && b.expires_at) continue
      if (f.locationId && b.location_id !== f.locationId) continue
      out.push({ batch: b, product: it.product })
    }
  }
  return out.sort((a, b) => a.product.name.localeCompare(b.product.name, 'da') || (a.batch.expires_at ?? '').localeCompare(b.batch.expires_at ?? ''))
}

/** Split ids into request-sized chunks (the API takes at most 500 per call). */
export function chunk<T>(xs: T[], size = 500): T[][] {
  const out: T[][] = []
  for (let i = 0; i < xs.length; i += size) out.push(xs.slice(i, i + size))
  return out
}
