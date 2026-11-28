// "Add without barcode": find or create a product by name, then queue an `add` op (offline capable for existing products).
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, WifiOff } from 'lucide-react'
import { get, isNetworkError, post, qs } from '../api/client'
import type { Location, Product, UUID } from '../api/types'
import { enqueueOp, getStore, useSyncStatus } from '../offline'
import { useDebounced } from '../hooks/useDebounced'
import { Button, Field, Input, Modal, Select } from './ui'
import { ProductThumb } from './ProductThumb'
import { cn } from '../lib/format'

export interface ManualAddSheetProps {
  open: boolean
  onClose: () => void
  /** Preselected location (null = automatic, like scanning). */
  defaultLocationId?: UUID | null
  /** Locations to offer; defaults to the offline store's cached list. */
  locations?: Location[]
  /** Called after the op is durably queued. */
  onAdded?: (product: Product, quantity: number) => void
  onError?: (message: string) => void
}

const MAX_QTY = 100_000

export function parseQty(s: string): number | null {
  const n = Number(s.trim().replace(',', '.'))
  if (!Number.isFinite(n) || n <= 0 || n > MAX_QTY) return null
  return Math.round(n * 1000) / 1000
}

async function searchProducts(q: string): Promise<{ items: Product[]; offline: boolean }> {
  try {
    return { items: await get<Product[]>(`/products${qs({ q, limit: 20 })}`), offline: false }
  } catch (e) {
    if (!isNetworkError(e)) throw e
    return { items: await getStore().searchProducts(q, 20), offline: true }
  }
}

export function ManualAddSheet({ open, onClose, defaultLocationId = null, locations: given, onAdded, onError }: ManualAddSheetProps) {
  const { t } = useTranslation()
  const sync = useSyncStatus()
  const [name, setName] = useState('')
  const [results, setResults] = useState<Product[]>([])
  const [searching, setSearching] = useState(false)
  const [product, setProduct] = useState<Product | null>(null)
  const [qty, setQty] = useState('1')
  const [locationId, setLocationId] = useState<string>(defaultLocationId ?? '')
  const [expiry, setExpiry] = useState('')
  const [cached, setCached] = useState<Location[]>([])
  const locations = [...(given ?? cached)].filter((l) => !l.deleted_at).sort((a, b) => a.sort_order - b.sort_order)
  const [busy, setBusy] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const debounced = useDebounced(name.trim(), 200)

  // fresh form each time it opens
  useEffect(() => {
    if (!open) return
    setName('')
    setResults([])
    setProduct(null)
    setQty('1')
    setExpiry('')
    setCreateError(null)
    setLocationId(defaultLocationId ?? '')
  }, [open, defaultLocationId])

  const needCached = open && !given
  useEffect(() => {
    if (!needCached) return
    void getStore()
      .getLocations()
      .then(setCached)
      .catch(() => setCached([]))
  }, [needCached])

  useEffect(() => {
    if (!open || product || !debounced) {
      setResults([])
      return
    }
    let alive = true
    setSearching(true)
    searchProducts(debounced)
      .then((r) => alive && setResults(r.items))
      .catch(() => alive && setResults([]))
      .finally(() => alive && setSearching(false))
    return () => {
      alive = false
    }
  }, [open, product, debounced])

  const trimmed = name.trim()
  const exact = results.some((p) => p.name.trim().toLocaleLowerCase() === trimmed.toLocaleLowerCase())
  const quantity = parseQty(qty)

  const create = async () => {
    if (!trimmed) return
    if (!sync.online) {
      setCreateError(t('manualAdd.needsConnection'))
      return
    }
    setBusy(true)
    setCreateError(null)
    try {
      const p = await post<Product>('/products', { name: trimmed })
      await getStore().cacheProduct(p).catch(() => undefined)
      setProduct(p)
    } catch (e) {
      setCreateError(isNetworkError(e) ? t('manualAdd.needsConnection') : t('manualAdd.createFailed'))
    } finally {
      setBusy(false)
    }
  }

  const submit = async () => {
    if (!product || quantity == null) return
    setBusy(true)
    try {
      await enqueueOp({
        type: 'add',
        product_id: product.id,
        quantity,
        location_id: locationId || null,
        expires_at: expiry || null,
      })
      onAdded?.(product, quantity)
      onClose()
    } catch {
      onError?.(t('manualAdd.addFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    // the scanner screen is white-on-dark: pin the text colour for the light sheet
    <div className="text-ink-900">
      <Modal
        open={open}
        onClose={onClose}
        title={t('manualAdd.title')}
        footer={
          product && (
            <>
              <Button variant="ghost" onClick={onClose}>
                {t('common.cancel')}
              </Button>
              <Button variant="primary" loading={busy} disabled={quantity == null} onClick={() => void submit()} data-testid="manual-add-submit">
                <Plus className="size-4" /> {t('manualAdd.add')}
              </Button>
            </>
          )
        }
      >
        {!product ? (
          <div className="space-y-3">
            <Field label={t('manualAdd.name')}>
              {(id) => (
                <Input
                  id={id}
                  autoFocus
                  autoComplete="off"
                  value={name}
                  maxLength={200}
                  onChange={(e) => {
                    setName(e.target.value)
                    setCreateError(null)
                  }}
                  placeholder={t('manualAdd.namePlaceholder')}
                  data-testid="manual-add-name"
                />
              )}
            </Field>
            {!sync.online && (
              <p className="flex items-center gap-2 text-sm text-ink-500">
                <WifiOff className="size-4" aria-hidden /> {t('manualAdd.offlineHint')}
              </p>
            )}
            {trimmed && (
              <ul className="divide-y divide-cream-200 overflow-hidden rounded-2xl ring-1 ring-cream-200" role="listbox" aria-label={t('manualAdd.results')}>
                {results.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={false}
                      onClick={() => setProduct(p)}
                      className="flex min-h-14 w-full items-center gap-3 px-3 py-2 text-left hover:bg-cream-200/70"
                    >
                      <ProductThumb name={p.name} src={p.image_url} className="size-10 shrink-0" />
                      <span className="min-w-0">
                        <span className="block truncate font-semibold">{p.name}</span>
                        {p.brand && <span className="block truncate text-sm text-ink-500">{p.brand}</span>}
                      </span>
                    </button>
                  </li>
                ))}
                {searching && results.length === 0 && <li className="px-3 py-3 text-sm text-ink-500">{t('manualAdd.searching')}</li>}
                {!exact && (
                  <li>
                    <button
                      type="button"
                      onClick={() => void create()}
                      disabled={busy}
                      data-testid="manual-add-create"
                      className={cn('flex min-h-14 w-full items-center gap-3 px-3 py-2 text-left font-semibold text-leaf-600 hover:bg-cream-200/70 disabled:opacity-50')}
                    >
                      <Plus className="size-5 shrink-0" aria-hidden /> {t('manualAdd.create', { name: trimmed })}
                    </button>
                  </li>
                )}
              </ul>
            )}
            {createError && (
              <p role="alert" className="text-sm font-medium text-tomato-600">
                {createError}
              </p>
            )}
          </div>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              void submit()
            }}
          >
            <div className="flex items-center gap-3 rounded-2xl bg-cream-100 p-3">
              <ProductThumb name={product.name} src={product.image_url} className="size-12 shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold" data-testid="manual-add-product">{product.name}</span>
                {product.brand && <span className="block truncate text-sm text-ink-500">{product.brand}</span>}
              </span>
              <Button size="sm" variant="ghost" onClick={() => setProduct(null)}>
                {t('manualAdd.change')}
              </Button>
            </div>
            <Field label={t('manualAdd.quantity')} hint={quantity == null ? t('manualAdd.invalidQuantity') : undefined}>
              {(id) => (
                <Input id={id} inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} data-testid="manual-add-qty" />
              )}
            </Field>
            <Field label={t('manualAdd.location')}>
              {(id) => (
                <Select id={id} value={locationId} onChange={(e) => setLocationId(e.target.value)} data-testid="manual-add-location">
                  <option value="">{t('manualAdd.locationAuto')}</option>
                  {locations.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t('manualAdd.expiry')}>
              {(id) => <Input id={id} type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} data-testid="manual-add-expiry" />}
            </Field>
            {/* lets Enter submit */}
            <button type="submit" hidden />
          </form>
        )}
      </Modal>
    </div>
  )
}
