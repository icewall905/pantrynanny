import { uuid } from '../offline'
import { useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Camera, CalendarPlus, ChevronLeft, Pencil, RefreshCw, ShoppingBasket, Trash2, Undo2 } from 'lucide-react'
import { ApiError, del, get, patch, post } from '../api/client'
import { useCategories, useInvalidateStock, useInventoryDetail, useLocations } from '../api/queries'
import type { InventoryItem, Product, StockBatch, Transaction } from '../api/types'
import { ExpiryBadge } from '../components/ExpiryBadge'
import { ProductThumb } from '../components/ProductThumb'
import { conflictProduct, ProductForm } from '../components/ProductForm'
import { QuantityStepper } from '../components/QuantityStepper'
import { ExpiryDialog, useAddToShopping } from '../components/StockDialogs'
import { useToast } from '../components/Toast'
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, Select, Skeleton } from '../components/ui'
import { useAuth, useSettings } from '../auth/AuthProvider'
import { useStockOps } from '../hooks/useStock'
import { formatDateTime, formatQty } from '../lib/format'
import { apiErrorText } from '../lib/opError'

/** EAN-13/8 or UPC of a product the open databases don't know yet (we named it ourselves). */
function contributableCode(p: Product): string | null {
  if (p.status !== 'known' || !['user', 'placeholder'].includes(p.source)) return null
  const gtin = p.barcodes.map((b) => b.code).find((c) => /^\d{14}$/.test(c))
  return gtin ? (gtin.startsWith('0') ? gtin.slice(1) : gtin) : null // GTIN-14 -> EAN-13
}

function attribution(p: Product, off: string): string | null {
  if (p.source_attribution) return p.source_attribution
  if (p.source === 'openfoodfacts') return off
  return null
}

export default function ProductDetailPage() {
  const { id = '' } = useParams()
  const { t, i18n } = useTranslation()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const { isAdmin } = useAuth()
  const { allow_negative_stock } = useSettings()
  const q = useInventoryDetail(id)
  const locs = useLocations()
  const cats = useCategories()
  const invalidate = useInvalidateStock()
  const { adjustBy, setCount, move } = useStockOps()
  const addShop = useAddToShopping()
  const photoRef = useRef<HTMLInputElement>(null)
  const [editing, setEditing] = useState(false)
  const [conflict, setConflict] = useState<Product | null>(null)
  const [expiryBatch, setExpiryBatch] = useState<StockBatch | null>(null)
  const [countOpen, setCountOpen] = useState(false)
  const [countValue, setCountValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)

  const refreshAll = () => {
    void qc.invalidateQueries({ queryKey: ['inventory-detail', id] })
    void qc.invalidateQueries({ queryKey: ['inventory'] })
    void qc.invalidateQueries({ queryKey: ['products'] })
  }

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      patch<Product>(`/products/${id}`, body, { headers: { 'If-Match': String(q.data!.product.version) } }),
    onSuccess: () => {
      setEditing(false)
      setConflict(null)
      refreshAll()
      toast.push(t('common.saved'), 'success')
    },
    onError: (e) => {
      const c = conflictProduct(e)
      if (c || (e instanceof ApiError && e.status === 409)) {
        setConflict(c ?? q.data!.product)
        toast.push(t('product.conflictTitle'), 'error')
      } else toast.push(t('common.saveFailed'), 'error')
    },
  })

  const photo = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return post(`/products/${id}/photo`, fd)
    },
    onSuccess: () => {
      refreshAll()
      toast.push(t('common.saved'), 'success')
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })

  const undo = useMutation({
    mutationFn: (tx: Transaction) => post(`/transactions/${tx.id}/undo`, { client_op_id: uuid() }),
    onSuccess: () => {
      void invalidate()
      toast.push(t('product.undone'), 'success')
    },
    onError: (e) =>
      toast.push(apiErrorText(t, e, t('common.saveFailed')), 'error'),
  })

  const refresh = useMutation({
    mutationFn: () => post(`/products/${id}/refresh`),
    onSuccess: () => {
      refreshAll()
      toast.push(t('product.refreshed'), 'success')
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })

  const remove = useMutation({
    mutationFn: () => del(`/products/${id}`),
    onSuccess: () => {
      void invalidate()
      void qc.invalidateQueries({ queryKey: ['products'] })
      nav('/inventory', { replace: true })
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })

  if (q.isLoading) return <Skeleton className="h-96 w-full" />
  if (q.isError) {
    if (q.error instanceof ApiError && q.error.status === 404)
      return <EmptyState title={t('product.notFound')} action={<Link className="font-semibold text-leaf-700" to="/inventory">{t('nav.inventory')}</Link>} />
    return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  }
  const item = q.data!
  const p = item.product
  const unit = p.stock_unit === 'pcs' ? undefined : t(`units.${p.stock_unit}`)
  const locName = (lid: string | null) => locs.data?.find((l) => l.id === lid)?.name ?? '—'
  const attr = attribution(p, t('product.offAttribution'))
  const asItem: InventoryItem = item
  const nutrition = p.nutrition && Object.keys(p.nutrition).length ? Object.entries(p.nutrition) : []
  const txLabel = (tx: Transaction) => t(`txn.${tx.type}`)

  return (
    <div className="space-y-4">
      <Link to="/inventory" className="inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-ink-700">
        <ChevronLeft className="size-4" /> {t('nav.inventory')}
      </Link>

      <Card className="flex flex-col gap-4 sm:flex-row">
        <div className="relative shrink-0 self-start">
          <ProductThumb name={p.name} src={p.image_url} className="size-32 text-5xl sm:size-40" />
          <button
            aria-label={t('product.changePhoto')}
            onClick={() => photoRef.current?.click()}
            className="absolute -bottom-2 -right-2 grid size-11 place-items-center rounded-full bg-surface shadow-md"
          >
            <Camera className="size-5" />
          </button>
          <input
            ref={photoRef}
            type="file"
            accept="image/*"
            capture="environment"
            hidden
            data-testid="photo-input"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) photo.mutate(f)
              e.target.value = ''
            }}
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <h1 className="text-2xl font-extrabold">{p.name}</h1>
              <p className="text-ink-500">{[p.brand, p.package_size ? `${formatQty(p.package_size, i18n.language)} ${p.package_unit ? t(`units.${p.package_unit}`) : ''}` : null].filter(Boolean).join(' · ')}</p>
            </div>
            {p.status !== 'known' && <Badge tone="info">{t(`status.${p.status}`)}</Badge>}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <QuantityStepper
              name={p.name}
              value={item.total_quantity}
              unit={unit}
              disableMinus={!allow_negative_stock && item.total_quantity <= 0}
              onChange={(d) => adjustBy.mutate({ productId: p.id, delta: d })}
            />
            <Button
              onClick={() => {
                setCountValue(String(item.total_quantity))
                setCountOpen(true)
              }}
            >
              {t('product.setCount')}
            </Button>
            <Button onClick={() => addShop.mutate([asItem])}>
              <ShoppingBasket className="size-4" /> {t('inventory.addToShopping')}
            </Button>
          </div>
          <RunOutLine productId={p.id} />
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setEditing(true)}>
              <Pencil className="size-4" /> {t('common.edit')}
            </Button>
            <Button size="sm" loading={refresh.isPending} onClick={() => refresh.mutate()}>
              <RefreshCw className="size-4" /> {t('product.refresh')}
            </Button>
            {isAdmin && (
              <Button size="sm" variant="ghost" className="text-tomato-600" onClick={() => setConfirmDelete(true)}>
                <Trash2 className="size-4" /> {t('common.delete')}
              </Button>
            )}
          </div>
        </div>
      </Card>

      <Card>
        <h2 className="mb-3 text-lg font-bold">{t('product.batches')}</h2>
        {item.batches.filter((b) => b.quantity > 0).length === 0 ? (
          <p className="text-sm text-ink-500">{t('product.noBatches')}</p>
        ) : (
          <ul className="divide-y divide-cream-200">
            {item.batches
              .filter((b) => b.quantity > 0)
              .map((b) => (
                <li key={b.id} className="flex flex-wrap items-center gap-3 py-3">
                  <span className="w-16 text-lg font-bold tabular-nums">
                    {formatQty(b.quantity, i18n.language)} {unit}
                  </span>
                  <Select
                    aria-label={t('inventory.location')}
                    className="w-auto!"
                    value={b.location_id}
                    onChange={(e) =>
                      move.mutate({ item: { ...asItem, batches: [b] }, toLocationId: e.target.value })
                    }
                  >
                    {locs.data?.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name}
                      </option>
                    ))}
                  </Select>
                  <ExpiryBadge date={b.expires_at} />
                  <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setExpiryBatch(b)}>
                    <CalendarPlus className="size-4" /> {t('inventory.setExpiry')}
                  </Button>
                </li>
              ))}
          </ul>
        )}
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-lg font-bold">{t('product.details')}</h2>
          <dl className="space-y-2 text-sm">
            <Row label={t('product.category')} value={cats.data?.find((c) => c.id === p.category_id)?.name ?? '—'} />
            <Row label={t('product.defaultLocation')} value={locName(p.default_location_id)} />
            <Row label={t('product.barcodes')} value={p.barcodes.map((b) => b.raw).join(', ') || '—'} />
            {p.aliases.length > 0 && <Row label={t('product.aliases')} value={p.aliases.join(', ')} />}
            {p.min_stock != null && <Row label={t('product.minStock')} value={String(p.min_stock)} />}
            {p.allergens.length > 0 && <Row label={t('product.allergens')} value={p.allergens.join(', ')} />}
            {p.ingredients && <Row label={t('product.ingredients')} value={p.ingredients} />}
            {p.description && <Row label={t('product.description')} value={p.description} />}
          </dl>
          {nutrition.length > 0 && (
            <>
              <h3 className="mb-1 mt-4 text-sm font-bold">{t('product.nutrition')}</h3>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                {nutrition.map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2 border-b border-cream-200 py-1">
                    <dt className="text-ink-500">{k.replace(/_/g, ' ')}</dt>
                    <dd className="font-medium">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
          {attr && <p className="mt-4 text-xs text-ink-500">{attr}</p>}
          {contributableCode(p) && (
            <p className="mt-4 text-xs text-ink-500" data-testid="off-contribute">
              {t('product.offContribute')}{' '}
              {/* only a link: nothing is uploaded automatically */}
              <a
                href={`https://world.openfoodfacts.org/product/${contributableCode(p)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-semibold text-leaf-600 hover:underline"
              >
                {t('product.offContributeLink')}
              </a>
            </p>
          )}
        </Card>

        <Card>
          <h2 className="mb-3 text-lg font-bold">{t('product.history')}</h2>
          {item.transactions.length === 0 ? (
            <p className="text-sm text-ink-500">{t('product.noHistory')}</p>
          ) : (
            <ul className="divide-y divide-cream-200">
              {item.transactions.map((tx) => (
                <li key={tx.id} className="flex items-center gap-3 py-2.5 text-sm">
                  <span className={`w-14 text-right font-bold tabular-nums ${tx.quantity_delta < 0 ? 'text-tomato-600' : 'text-leaf-700'}`}>
                    {tx.quantity_delta > 0 ? '+' : ''}
                    {formatQty(tx.quantity_delta, i18n.language)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className={tx.undone ? 'line-through opacity-60' : ''}>
                      {txLabel(tx)}
                      {tx.reason ? ` · ${tx.reason}` : ''}
                    </div>
                    <div className="truncate text-xs text-ink-500">
                      {formatDateTime(tx.occurred_at, i18n.language)}
                      {tx.device_name ? ` · ${tx.device_name}` : ''}
                    </div>
                  </div>
                  {!tx.undone && tx.type !== 'undo' && (
                    <Button size="sm" variant="ghost" aria-label={t('product.undoTx')} loading={undo.isPending && undo.variables?.id === tx.id} onClick={() => undo.mutate(tx)}>
                      <Undo2 className="size-4" /> {t('product.undo')}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Modal open={editing} onClose={() => setEditing(false)} title={t('common.edit')}>
        <ProductForm
          key={conflict?.version ?? p.version}
          initial={conflict ?? p}
          saving={save.isPending}
          conflict={conflict}
          onReload={() => {
            setConflict(null)
            refreshAll()
          }}
          onSubmit={(b) => save.mutate(b)}
          onCancel={() => setEditing(false)}
        />
      </Modal>

      <Modal
        open={countOpen}
        onClose={() => setCountOpen(false)}
        title={t('product.setCount')}
        footer={
          <>
            <Button onClick={() => setCountOpen(false)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              loading={setCount.isPending}
              onClick={() => {
                const target = Number(countValue.replace(',', '.'))
                if (Number.isFinite(target) && target >= 0 && target !== item.total_quantity)
                  setCount.mutate({ productId: p.id, current: item.total_quantity, target })
                setCountOpen(false)
              }}
            >
              {t('common.save')}
            </Button>
          </>
        }
      >
        <p className="mb-3 text-sm text-ink-500">{t('product.setCountHint')}</p>
        <Field label={t('product.actualCount')}>
          {(fid) => <Input id={fid} inputMode="decimal" autoFocus value={countValue} onChange={(e) => setCountValue(e.target.value)} />}
        </Field>
      </Modal>

      <ExpiryDialog item={expiryBatch ? asItem : null} batch={expiryBatch ?? undefined} onClose={() => setExpiryBatch(null)} />

      <Modal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t('common.delete')}
        footer={
          <>
            <Button onClick={() => setConfirmDelete(false)}>{t('common.cancel')}</Button>
            <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>
              {t('common.delete')}
            </Button>
          </>
        }
      >
        <p className="text-sm">{t('product.deleteConfirm', { name: p.name })}</p>
      </Modal>
    </div>
  )
}

function Row({ label, value }: { label: string; value?: string }) {
  if (value === undefined) return null
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2">
      <dt className="text-ink-500">{label}</dt>
      <dd className="break-words">{value}</dd>
    </div>
  )
}

/** "At your usual pace this lasts ~N more days" – only when there is enough history. */
function RunOutLine({ productId }: { productId: string }) {
  const { t } = useTranslation()
  const q = useQuery({
    queryKey: ['stats', 'runout', productId],
    queryFn: () => get<{ days_left: number; per_day: number; confidence: 'medium' | 'high' }[]>(`/stats/runout?product_id=${productId}`),
    staleTime: 300_000,
  })
  const f = q.data?.[0]
  if (!f) return null
  return (
    <p className="mt-3 text-sm text-ink-500" data-testid="runout-line">
      {t('product.runOut', { count: Math.max(1, Math.round(f.days_left)) })} · {t(`dashboard.conf_${f.confidence}`)}
    </p>
  )
}
