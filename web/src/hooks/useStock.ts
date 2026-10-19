import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { enqueueOp } from '../offline'
import type { InventoryDetail, InventoryItem, UUID } from '../api/types'
import { useInvalidateStock } from '../api/queries'
import { useToast } from '../components/Toast'

type Snapshot = [readonly unknown[], unknown][]

function patchTotals(
  data: unknown,
  productId: UUID,
  delta: number,
): unknown {
  if (Array.isArray(data)) {
    return (data as InventoryItem[]).map((it) =>
      it.product.id === productId ? { ...it, total_quantity: Math.max(0, it.total_quantity + delta) } : it,
    )
  }
  const d = data as InventoryDetail | undefined
  if (d && d.product?.id === productId) return { ...d, total_quantity: Math.max(0, d.total_quantity + delta) }
  return data
}

/** All stock-changing UI actions. Every change goes through enqueueOp (idempotent, offline capable). */
export function useStockOps() {
  const qc = useQueryClient()
  const toast = useToast()
  const { t } = useTranslation()
  const invalidate = useInvalidateStock()

  const adjustBy = useMutation({
    mutationFn: (v: { productId: UUID; delta: number; locationId?: UUID | null }) =>
      enqueueOp(
        v.delta > 0
          ? { type: 'add', product_id: v.productId, quantity: v.delta, location_id: v.locationId ?? null }
          : { type: 'remove', product_id: v.productId, quantity: -v.delta, location_id: v.locationId ?? null },
      ),
    onMutate: async (v) => {
      await Promise.all([
        qc.cancelQueries({ queryKey: ['inventory'] }),
        qc.cancelQueries({ queryKey: ['inventory-detail'] }),
      ])
      const snapshot: Snapshot = [
        ...qc.getQueriesData({ queryKey: ['inventory'] }),
        ...qc.getQueriesData({ queryKey: ['inventory-detail'] }),
      ]
      for (const [key] of snapshot) qc.setQueryData(key, (old: unknown) => patchTotals(old, v.productId, v.delta))
      return { snapshot }
    },
    onError: (_e, _v, ctx) => {
      ctx?.snapshot.forEach(([key, data]) => qc.setQueryData(key, data))
      toast.push(t('inventory.changeFailed'), 'error')
    },
    onSettled: () => void invalidate(),
  })

  const setCount = useMutation({
    mutationFn: (v: { productId: UUID; current: number; target: number }) =>
      enqueueOp({
        type: 'adjust',
        product_id: v.productId,
        quantity: Math.round((v.target - v.current) * 1000) / 1000,
        reason: 'correction',
      }),
    onSuccess: () => toast.push(t('product.countSaved'), 'success'),
    onError: () => toast.push(t('inventory.changeFailed'), 'error'),
    onSettled: () => void invalidate(),
  })

  const move = useMutation({
    mutationFn: async (v: { item: InventoryItem; toLocationId: UUID }) => {
      for (const b of v.item.batches) {
        if (b.location_id === v.toLocationId || b.quantity <= 0) continue
        await enqueueOp({
          type: 'move',
          product_id: v.item.product.id,
          quantity: b.quantity,
          location_id: b.location_id,
          to_location_id: v.toLocationId,
        })
      }
    },
    onSuccess: () => toast.push(t('inventory.moved'), 'success'),
    onError: () => toast.push(t('inventory.changeFailed'), 'error'),
    onSettled: () => void invalidate(),
  })

  const removeAll = useMutation({
    mutationFn: async (items: InventoryItem[]) => {
      for (const it of items) {
        if (it.total_quantity > 0)
          await enqueueOp({ type: 'remove', product_id: it.product.id, quantity: it.total_quantity })
      }
    },
    onSuccess: () => toast.push(t('inventory.removed'), 'success'),
    onError: () => toast.push(t('inventory.changeFailed'), 'error'),
    onSettled: () => void invalidate(),
  })

  return { adjustBy, setCount, move, removeAll }
}
