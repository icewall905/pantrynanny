import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../api/client'
import { useCategories, useLocations } from '../api/queries'
import { UNITS, type Product, type Unit } from '../api/types'
import { Button, Field, Input, Select, Textarea } from './ui'

export interface ProductDraft {
  name: string
  brand: string
  category_id: string
  default_location_id: string
  package_size: string
  package_unit: string
  stock_unit: Unit
  min_stock: string
  description: string
  aliases: string
  barcode: string
}

export function draftFrom(p?: Partial<Product>): ProductDraft {
  return {
    name: p?.name ?? '',
    brand: p?.brand ?? '',
    category_id: p?.category_id ?? '',
    default_location_id: p?.default_location_id ?? '',
    package_size: p?.package_size != null ? String(p.package_size) : '',
    package_unit: p?.package_unit ?? '',
    stock_unit: p?.stock_unit ?? 'pcs',
    min_stock: p?.min_stock != null ? String(p.min_stock) : '',
    description: p?.description ?? '',
    aliases: (p?.aliases ?? []).join(', '),
    barcode: '',
  }
}

const num = (s: string) => (s.trim() === '' ? null : Number(s.replace(',', '.')))

export function draftToPayload(d: ProductDraft, creating: boolean): Record<string, unknown> {
  const body: Record<string, unknown> = {
    name: d.name.trim(),
    brand: d.brand.trim() || null,
    category_id: d.category_id || null,
    default_location_id: d.default_location_id || null,
    package_size: num(d.package_size),
    package_unit: d.package_unit || null,
    stock_unit: d.stock_unit,
    min_stock: num(d.min_stock),
    description: d.description.trim() || null,
    aliases: d.aliases.split(',').map((s) => s.trim()).filter(Boolean),
  }
  if (creating && d.barcode.trim()) body.barcodes = [d.barcode.trim()]
  return body
}

export function ProductForm({
  initial,
  creating,
  saving,
  conflict,
  onReload,
  onSubmit,
  onCancel,
}: {
  initial?: Product
  creating?: boolean
  saving?: boolean
  conflict?: Product | null
  onReload?: (server: Product) => void
  onSubmit: (body: Record<string, unknown>) => void
  onCancel?: () => void
}) {
  const { t } = useTranslation()
  const cats = useCategories()
  const locs = useLocations()
  const [d, setD] = useState<ProductDraft>(() => draftFrom(initial))
  const set = <K extends keyof ProductDraft>(k: K, v: ProductDraft[K]) => setD((x) => ({ ...x, [k]: v }))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!d.name.trim()) return
    onSubmit(draftToPayload(d, !!creating))
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      {conflict && (
        <div role="alert" className="rounded-2xl bg-honey-50 p-4 text-sm ring-1 ring-honey-400/50">
          <p className="font-semibold">{t('product.conflictTitle')}</p>
          <p className="mb-2 text-ink-700">{t('product.conflictHint', { name: conflict.name, version: conflict.version })}</p>
          <Button size="sm" onClick={() => onReload?.(conflict)}>
            {t('product.reload')}
          </Button>
        </div>
      )}
      <Field label={t('product.name')}>
        {(id) => <Input id={id} required value={d.name} onChange={(e) => set('name', e.target.value)} />}
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('product.brand')}>{(id) => <Input id={id} value={d.brand} onChange={(e) => set('brand', e.target.value)} />}</Field>
        <Field label={t('product.category')}>
          {(id) => (
            <Select id={id} value={d.category_id} onChange={(e) => set('category_id', e.target.value)}>
              <option value="">—</option>
              {cats.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('product.packageSize')}>
          {(id) => <Input id={id} inputMode="decimal" value={d.package_size} onChange={(e) => set('package_size', e.target.value)} />}
        </Field>
        <Field label={t('product.packageUnit')}>
          {(id) => (
            <Select id={id} value={d.package_unit} onChange={(e) => set('package_unit', e.target.value)}>
              <option value="">—</option>
              {UNITS.map((u) => (
                <option key={u} value={u}>
                  {t(`units.${u}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('product.stockUnit')}>
          {(id) => (
            <Select id={id} value={d.stock_unit} onChange={(e) => set('stock_unit', e.target.value as Unit)}>
              {UNITS.map((u) => (
                <option key={u} value={u}>
                  {t(`units.${u}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('product.minStock')} hint={t('product.minStockHint')}>
          {(id) => <Input id={id} inputMode="decimal" value={d.min_stock} onChange={(e) => set('min_stock', e.target.value)} />}
        </Field>
        <Field label={t('product.defaultLocation')}>
          {(id) => (
            <Select id={id} value={d.default_location_id} onChange={(e) => set('default_location_id', e.target.value)}>
              <option value="">—</option>
              {locs.data?.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {creating && (
          <Field label={t('product.barcode')}>
            {(id) => <Input id={id} inputMode="numeric" value={d.barcode} onChange={(e) => set('barcode', e.target.value)} />}
          </Field>
        )}
      </div>
      <Field label={t('product.aliases')} hint={t('product.aliasesHint')}>
        {(id) => <Input id={id} value={d.aliases} onChange={(e) => set('aliases', e.target.value)} />}
      </Field>
      <Field label={t('product.description')}>
        {(id) => <Textarea id={id} rows={3} value={d.description} onChange={(e) => set('description', e.target.value)} />}
      </Field>
      <div className="flex justify-end gap-2">
        {onCancel && <Button onClick={onCancel}>{t('common.cancel')}</Button>}
        <Button type="submit" variant="primary" loading={saving} disabled={!d.name.trim()}>
          {t('common.save')}
        </Button>
      </div>
    </form>
  )
}

/** Extract the server copy from a 409 response (contract: 409 returns the current Product). */
export function conflictProduct(e: unknown): Product | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null
  const b = e.body as { product?: Product; current?: Product } & Partial<Product>
  const p = b.product ?? b.current ?? (b.id ? (b as Product) : null)
  return p ?? null
}
