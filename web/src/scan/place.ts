import type { Category, Location, Product } from '../api/types'

/**
 * Where an add without an explicit location went (same order as the server: requested ->
 * product -> category -> household default by is_default desc, sort_order, then list order;
 * the server's last tie-break is created_at, which the API does not expose).
 */
export function resolvedLocation(
  requested: string | null,
  product: Product | null,
  category: Category | undefined,
  locations: Location[],
): string | null {
  const live = (id: string | null | undefined) => (id && locations.some((l) => l.id === id) ? id : null)
  return (
    live(requested) ??
    live(product?.default_location_id) ??
    live(category?.default_location_id) ??
    householdDefault(locations)
  )
}

export function householdDefault(locations: Location[]): string | null {
  const best = locations
    .map((l, i) => ({ l, i }))
    .sort((a, b) => Number(b.l.is_default) - Number(a.l.is_default) || a.l.sort_order - b.l.sort_order || a.i - b.i)[0]
  return best?.l.id ?? null
}
