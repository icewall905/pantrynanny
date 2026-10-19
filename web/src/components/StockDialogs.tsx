import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { patch, post } from '../api/client'
import { useInvalidateStock, useLocations } from '../api/queries'
import type { InventoryItem, StockBatch } from '../api/types'
import { useStockOps } from '../hooks/useStock'
import { Button, Chip, Field, Input, Modal, Select } from './ui'
import { todayISO } from '../lib/format'
import { useToast } from './Toast'

export function MoveDialog({ items, onClose }: { items: InventoryItem[] | null; onClose: () => void }) {
  const { t } = useTranslation()
  const locs = useLocations()
  const { move } = useStockOps()
  const [to, setTo] = useState('')
  const run = async () => {
    for (const item of items ?? []) await move.mutateAsync({ item, toLocationId: to }).catch(() => {})
    onClose()
  }
  return (
    <Modal
      open={!!items}
      onClose={onClose}
      title={t('inventory.moveTitle', { count: items?.length ?? 0 })}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" disabled={!to} loading={move.isPending} onClick={() => void run()}>
            {t('inventory.move')}
          </Button>
        </>
      }
    >
      <Field label={t('inventory.moveTo')}>
        {(id) => (
          <Select id={id} value={to} onChange={(e) => setTo(e.target.value)}>
            <option value="">{t('common.choose')}</option>
            {locs.data?.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
    </Modal>
  )
}

export function ExpiryDialog({
  item,
  batch,
  onClose,
}: {
  item: InventoryItem | null
  batch?: StockBatch
  onClose: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const invalidate = useInvalidateStock()
  const target = batch ?? item?.batches.find((b) => b.quantity > 0) ?? item?.batches[0]
  const [value, setValue] = useState<string | null>(null)
  const current = value ?? target?.expires_at ?? ''
  const save = useMutation({
    mutationFn: () => patch(`/batches/${target!.id}`, { expires_at: current || null }),
    onSuccess: () => {
      toast.push(t('common.saved'), 'success')
      void invalidate()
      onClose()
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  return (
    <Modal
      open={!!item && !!target}
      onClose={onClose}
      title={t('inventory.setExpiry')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <p className="mb-3 text-sm text-ink-500">{item?.product.name}</p>
      <Field label={t('inventory.expiryDate')}>
        {(id) => <Input id={id} type="date" value={current} onChange={(e) => setValue(e.target.value)} />}
      </Field>
      <div className="mt-3 flex flex-wrap gap-2" data-testid="expiry-quick">
        {[1, 3, 7, 14, 30].map((n) => (
          <Chip key={n} onClick={() => setValue(todayISO(new Date(Date.now() + n * 86_400_000)))}>
            {t('inventory.inDays', { count: n })}
          </Chip>
        ))}
        {current && <Chip onClick={() => setValue('')}>{t('inventory.noExpiry')}</Chip>}
      </div>
    </Modal>
  )
}

export function useAddToShopping() {
  const qc = useQueryClient()
  const toast = useToast()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: async (items: InventoryItem[]) => {
      for (const it of items)
        await post('/shopping', {
          product_id: it.product.id,
          name: it.product.name,
          quantity: 1,
          category_id: it.product.category_id,
        })
    },
    onSuccess: () => {
      toast.push(t('shopping.added'), 'success')
      void qc.invalidateQueries({ queryKey: ['shopping'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
}
