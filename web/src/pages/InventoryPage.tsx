import { memo, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { CalendarPlus, FolderInput, LayoutList, Layers, Package, Plus, Search, ShoppingBasket, Trash2, X } from 'lucide-react'
import { useCategories, useInventory, useLocations, type InventoryParams } from '../api/queries'
import type { InventoryItem, Location } from '../api/types'
import { useSettings } from '../auth/AuthProvider'
import { ExpiryBadge } from '../components/ExpiryBadge'
import { ProductThumb } from '../components/ProductThumb'
import { QuantityStepper } from '../components/QuantityStepper'
import { ExpiryDialog, MoveDialog, useAddToShopping } from '../components/StockDialogs'
import { Badge, Button, EmptyState, ErrorState, ListSkeleton, Menu, Modal, PageHeader, Select } from '../components/ui'
import { useStockOps } from '../hooks/useStock'
import { useDebounced } from '../hooks/useDebounced'
import { cn } from '../lib/format'

interface RowProps {
  item: InventoryItem
  selected: boolean
  onSelect: (id: string, v: boolean) => void
  onMove: (i: InventoryItem) => void
  onExpiry: (i: InventoryItem) => void
  onShop: (i: InventoryItem) => void
  onDelta: (i: InventoryItem, d: number) => void
  allowNegative: boolean
  locationNames: string
}

export const InventoryRow = memo(function InventoryRow({
  item,
  selected,
  onSelect,
  onMove,
  onExpiry,
  onShop,
  onDelta,
  allowNegative,
  locationNames,
}: RowProps) {
  const { t } = useTranslation()
  const p = item.product
  const unit = p.stock_unit === 'pcs' ? undefined : t(`units.${p.stock_unit}`)
  return (
    <li className="flex items-center gap-2 rounded-[var(--radius-card)] bg-white p-3 shadow-card sm:gap-3">
      <input
        type="checkbox"
        aria-label={t('inventory.select', { name: p.name })}
        checked={selected}
        onChange={(e) => onSelect(p.id, e.target.checked)}
        className="size-5 shrink-0 accent-leaf-600"
      />
      <Link to={`/products/${p.id}`} className="flex min-w-0 flex-1 items-center gap-3">
        <ProductThumb name={p.name} src={p.image_url} />
        <div className="min-w-0">
          <div className="truncate font-semibold">{p.name}</div>
          <div className="truncate text-xs text-ink-500">{[p.brand, locationNames].filter(Boolean).join(' · ')}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            <ExpiryBadge date={item.next_expiry} />
            {item.low_stock && <Badge tone="warn">{t('inventory.low')}</Badge>}
            {p.status !== 'known' && <Badge tone="info">{t('inventory.needsId')}</Badge>}
          </div>
        </div>
      </Link>
      <QuantityStepper
        name={p.name}
        value={item.total_quantity}
        unit={unit}
        disableMinus={!allowNegative && item.total_quantity <= 0}
        onChange={(d) => onDelta(item, d)}
      />
      <Menu
        label={t('inventory.actions', { name: p.name })}
        items={[
          { label: t('inventory.move'), icon: <FolderInput className="size-4" />, onClick: () => onMove(item) },
          { label: t('inventory.setExpiry'), icon: <CalendarPlus className="size-4" />, onClick: () => onExpiry(item) },
          { label: t('inventory.addToShopping'), icon: <ShoppingBasket className="size-4" />, onClick: () => onShop(item) },
        ]}
      />
    </li>
  )
})

export default function InventoryPage() {
  const { t } = useTranslation()
  const [sp, setSp] = useSearchParams()
  const [q, setQ] = useState(sp.get('q') ?? '')
  const dq = useDebounced(q, 250)
  const location_id = sp.get('location') ?? ''
  const category_id = sp.get('category') ?? ''
  const sort = (sp.get('sort') ?? 'name') as NonNullable<InventoryParams['sort']>
  const lowOnly = sp.get('low') === '1'
  const grouped = sp.get('group') === '1'
  const setParam = (k: string, v: string) =>
    setSp((prev) => {
      const n = new URLSearchParams(prev)
      if (v) n.set(k, v)
      else n.delete(k)
      return n
    }, { replace: true })

  const locs = useLocations()
  const cats = useCategories()
  const inv = useInventory({ q: dq || undefined, location_id: location_id || undefined, category_id: category_id || undefined, sort })
  const { adjustBy, removeAll } = useStockOps()
  const addShop = useAddToShopping()
  const { allow_negative_stock } = useSettings()

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [moveItems, setMoveItems] = useState<InventoryItem[] | null>(null)
  const [expiryItem, setExpiryItem] = useState<InventoryItem | null>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)

  const items = useMemo(() => (inv.data ?? []).filter((i) => !lowOnly || i.low_stock), [inv.data, lowOnly])
  const locById = useMemo(() => new Map((locs.data ?? []).map((l) => [l.id, l])), [locs.data])
  const names = (i: InventoryItem) =>
    [...new Set(i.batches.filter((b) => b.quantity > 0).map((b) => locById.get(b.location_id)?.name))].filter(Boolean).join(', ')
  const chosen = items.filter((i) => selected.has(i.product.id))

  const onSelect = (id: string, v: boolean) =>
    setSelected((s) => {
      const n = new Set(s)
      if (v) n.add(id)
      else n.delete(id)
      return n
    })

  const rowProps = (item: InventoryItem) => ({
    item,
    selected: selected.has(item.product.id),
    onSelect,
    onMove: (i: InventoryItem) => setMoveItems([i]),
    onExpiry: setExpiryItem,
    onShop: (i: InventoryItem) => addShop.mutate([i]),
    onDelta: (i: InventoryItem, d: number) => adjustBy.mutate({ productId: i.product.id, delta: d }),
    allowNegative: allow_negative_stock,
    locationNames: names(item),
  })

  const groups = useMemo(() => {
    if (!grouped) return null
    const out = new Map<string, { loc: Location | null; items: InventoryItem[] }>()
    for (const it of items) {
      const lids = [...new Set(it.batches.filter((b) => b.quantity > 0).map((b) => b.location_id))]
      for (const lid of lids.length ? lids : ['']) {
        const g = out.get(lid) ?? { loc: locById.get(lid) ?? null, items: [] }
        g.items.push(it)
        out.set(lid, g)
      }
    }
    return [...out.values()].sort((a, b) => (a.loc?.sort_order ?? 999) - (b.loc?.sort_order ?? 999))
  }, [grouped, items, locById])

  return (
    <>
      <PageHeader
        title={t('nav.inventory')}
        actions={
          <Link to="/products/new" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-leaf-600 px-4 text-sm font-semibold text-white hover:bg-leaf-700">
            <Plus className="size-4" /> {t('product.new')}
          </Link>
        }
      />
      <div className="sticky top-12 z-10 -mx-4 mb-4 space-y-2 bg-cream-100/95 px-4 pb-2 pt-1 backdrop-blur lg:top-0 lg:mx-0 lg:px-0">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-ink-500" aria-hidden />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('inventory.searchPlaceholder')}
            aria-label={t('inventory.search')}
            className="min-h-12 w-full rounded-2xl border-0 bg-white pl-11 pr-4 text-base shadow-card placeholder:text-ink-300"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Select aria-label={t('inventory.location')} className="w-auto" value={location_id} onChange={(e) => setParam('location', e.target.value)}>
            <option value="">{t('inventory.allLocations')}</option>
            {locs.data?.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </Select>
          <Select aria-label={t('inventory.category')} className="w-auto" value={category_id} onChange={(e) => setParam('category', e.target.value)}>
            <option value="">{t('inventory.allCategories')}</option>
            {cats.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Select aria-label={t('inventory.sort')} className="w-auto" value={sort} onChange={(e) => setParam('sort', e.target.value)}>
            {(['name', 'quantity', 'expiry', 'updated'] as const).map((s) => (
              <option key={s} value={s}>
                {t(`inventory.sort_${s}`)}
              </option>
            ))}
          </Select>
          <Button
            aria-pressed={lowOnly}
            variant={lowOnly ? 'primary' : 'secondary'}
            onClick={() => setParam('low', lowOnly ? '' : '1')}
          >
            {t('inventory.lowOnly')}
          </Button>
          <Button aria-pressed={grouped} onClick={() => setParam('group', grouped ? '' : '1')} variant={grouped ? 'primary' : 'secondary'}>
            {grouped ? <Layers className="size-4" /> : <LayoutList className="size-4" />}
            {t('inventory.grouped')}
          </Button>
        </div>
      </div>

      {selected.size > 0 && (
        <div className="pn-pop sticky top-28 z-10 mb-3 flex flex-wrap items-center gap-2 rounded-2xl bg-ink-900 p-2 pl-4 text-cream-50 shadow-lg lg:top-16">
          <span className="mr-auto text-sm font-semibold">{t('inventory.selected', { count: selected.size })}</span>
          <Button size="sm" onClick={() => setMoveItems(chosen)}>
            <FolderInput className="size-4" /> {t('inventory.move')}
          </Button>
          <Button size="sm" onClick={() => addShop.mutate(chosen)}>
            <ShoppingBasket className="size-4" /> {t('inventory.addToShopping')}
          </Button>
          <Button size="sm" variant="danger" onClick={() => setConfirmRemove(true)}>
            <Trash2 className="size-4" /> {t('inventory.removeStock')}
          </Button>
          <button aria-label={t('common.clear')} className="grid size-9 place-items-center rounded-lg hover:bg-white/10" onClick={() => setSelected(new Set())}>
            <X className="size-4" />
          </button>
        </div>
      )}

      {inv.isError ? (
        <ErrorState error={inv.error} onRetry={() => void inv.refetch()} />
      ) : inv.isLoading ? (
        <ListSkeleton />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Package className="size-8" />}
          title={dq ? t('inventory.noMatch') : t('inventory.empty')}
          hint={dq ? t('inventory.noMatchHint') : t('inventory.emptyHint')}
        />
      ) : groups ? (
        <div className="space-y-6">
          {groups.map((g) => (
            <section key={g.loc?.id ?? 'none'}>
              <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-ink-500">
                {g.loc?.name ?? t('inventory.noLocation')} <span className="font-normal">({g.items.length})</span>
              </h2>
              <ul className={cn('space-y-2')}>
                {g.items.map((i) => (
                  <InventoryRow key={i.product.id} {...rowProps(i)} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map((i) => (
            <InventoryRow key={i.product.id} {...rowProps(i)} />
          ))}
        </ul>
      )}

      <MoveDialog
        items={moveItems}
        onClose={() => {
          setMoveItems(null)
          setSelected(new Set())
        }}
      />
      <ExpiryDialog item={expiryItem} onClose={() => setExpiryItem(null)} />
      <Modal
        open={confirmRemove}
        onClose={() => setConfirmRemove(false)}
        title={t('inventory.removeStock')}
        footer={
          <>
            <Button onClick={() => setConfirmRemove(false)}>{t('common.cancel')}</Button>
            <Button
              variant="danger"
              loading={removeAll.isPending}
              onClick={() =>
                removeAll.mutate(chosen, {
                  onSettled: () => {
                    setConfirmRemove(false)
                    setSelected(new Set())
                  },
                })
              }
            >
              {t('inventory.removeStock')}
            </Button>
          </>
        }
      >
        <p className="text-sm">{t('inventory.removeConfirm', { count: chosen.length })}</p>
      </Modal>
    </>
  )
}
