import { useQuery, useQueryClient } from '@tanstack/react-query'
import { get, qs } from './client'
import type {
  AiStatus,
  Category,
  Dashboard,
  InventoryDetail,
  InventoryItem,
  Location,
  Product,
  ShoppingItem,
} from './types'

export const keys = {
  me: ['me'] as const,
  locations: ['locations'] as const,
  categories: ['categories'] as const,
  inventory: (p?: object) => ['inventory', p ?? {}] as const,
  inventoryDetail: (id: string) => ['inventory-detail', id] as const,
  products: (p?: object) => ['products', p ?? {}] as const,
  product: (id: string) => ['product', id] as const,
  dashboard: ['dashboard'] as const,
  shopping: ['shopping'] as const,
  suggestions: ['shopping-suggestions'] as const,
  stats: (days: number) => ['stats', days] as const,
  ai: ['ai-status'] as const,
}

export const useLocations = () =>
  useQuery({
    queryKey: keys.locations,
    queryFn: async () => (await get<Location[]>('/locations')).filter((l) => !l.deleted_at),
    staleTime: 60_000,
  })

export const useCategories = () =>
  useQuery({
    queryKey: keys.categories,
    queryFn: async () => (await get<Category[]>('/categories')).filter((c) => !c.deleted_at),
    staleTime: 60_000,
  })

export interface InventoryParams {
  q?: string
  location_id?: string
  category_id?: string
  sort?: 'name' | 'quantity' | 'expiry' | 'updated'
  include_empty?: boolean
}

export const useInventory = (p: InventoryParams) =>
  useQuery({
    queryKey: keys.inventory(p),
    queryFn: () => get<InventoryItem[]>(`/inventory${qs({ ...p })}`),
    placeholderData: (prev) => prev,
  })

export const useInventoryDetail = (id: string) =>
  useQuery({ queryKey: keys.inventoryDetail(id), queryFn: () => get<InventoryDetail>(`/inventory/${id}`) })

export const useProduct = (id: string) =>
  useQuery({ queryKey: keys.product(id), queryFn: () => get<Product>(`/products/${id}`) })

export const useDashboard = () => useQuery({ queryKey: keys.dashboard, queryFn: () => get<Dashboard>('/dashboard') })

export const useShopping = () => useQuery({ queryKey: keys.shopping, queryFn: () => get<ShoppingItem[]>('/shopping') })

export const useAiStatus = () =>
  useQuery({
    queryKey: keys.ai,
    queryFn: () => get<AiStatus>('/ai/status').catch(() => ({ enabled: false, reachable: false, model: null })),
    staleTime: 60_000,
  })

/** Invalidate everything that depends on stock levels. */
export function useInvalidateStock() {
  const qc = useQueryClient()
  return () =>
    Promise.all(
      ['inventory', 'inventory-detail', 'dashboard', 'shopping-suggestions', 'stats'].map((k) =>
        qc.invalidateQueries({ queryKey: [k] }),
      ),
    )
}
