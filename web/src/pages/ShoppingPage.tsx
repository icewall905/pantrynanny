import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Check, ClipboardCopy, Download, Lightbulb, Minus, PackageCheck, Plus, ShoppingBasket, Store, Trash2 } from 'lucide-react'
import { del, get, patch, post, qs } from '../api/client'
import { keys, useCategories, useShopping } from '../api/queries'
import type { InventoryItem, Product, ShoppingItem } from '../api/types'
import { useToast } from '../components/Toast'
import { Button, Card, Chip, EmptyState, ErrorState, Field, Input, ListSkeleton, Modal, PageHeader } from '../components/ui'
import { enqueueOp } from '../offline'
import { useInvalidateStock } from '../api/queries'
import { useDebounced } from '../hooks/useDebounced'
import { cn, formatQty, groupShopping, shoppingToText } from '../lib/format'

export function ShoppingRow({
  item,
  onToggle,
  onQty,
  onDelete,
  onEdit,
}: {
  item: ShoppingItem
  onToggle: (i: ShoppingItem) => void
  onQty: (i: ShoppingItem, q: number) => void
  onDelete: (i: ShoppingItem) => void
  onEdit?: (i: ShoppingItem) => void
}) {
  const { t, i18n } = useTranslation()
  return (
    <li className="flex min-h-16 items-center gap-3 py-2">
      <button
        role="checkbox"
        aria-checked={item.checked}
        aria-label={t('shopping.check', { name: item.name })}
        onClick={() => onToggle(item)}
        className={cn(
          'grid size-9 shrink-0 place-items-center rounded-xl border-2 transition-colors',
          item.checked ? 'border-leaf-600 bg-leaf-600 text-white' : 'border-ink-300 bg-surface',
        )}
      >
        {item.checked && <Check className="size-5" />}
      </button>
      <button
        type="button"
        disabled={!onEdit}
        onClick={() => onEdit?.(item)}
        aria-label={onEdit ? t('shopping.editItem', { name: item.name }) : undefined}
        className={cn('min-w-0 flex-1 text-left', item.checked && 'text-ink-300 line-through')}
      >
        <div className="truncate font-semibold">{item.name}</div>
        {(item.note || item.store) && (
          <div className="truncate text-xs text-ink-500">{[item.store, item.note].filter(Boolean).join(' · ')}</div>
        )}
      </button>
      <div className="flex items-center gap-1">
        <button aria-label={t('shopping.less', { name: item.name })} disabled={item.quantity <= 1} onClick={() => onQty(item, item.quantity - 1)} className="grid size-10 place-items-center rounded-lg hover:bg-cream-200 disabled:opacity-30">
          <Minus className="size-4" />
        </button>
        <span className="min-w-8 text-center font-bold tabular-nums">
          {formatQty(item.quantity, i18n.language)}
          {item.unit ? <span className="ml-0.5 text-xs font-normal text-ink-500">{t(`units.${item.unit}`)}</span> : null}
        </span>
        <button aria-label={t('shopping.more', { name: item.name })} onClick={() => onQty(item, item.quantity + 1)} className="grid size-10 place-items-center rounded-lg hover:bg-cream-200">
          <Plus className="size-4" />
        </button>
      </div>
      <button aria-label={t('common.delete')} onClick={() => onDelete(item)} className="grid size-10 place-items-center rounded-lg text-ink-300 hover:bg-tomato-50 hover:text-tomato-600">
        <Trash2 className="size-4" />
      </button>
    </li>
  )
}

export default function ShoppingPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const toast = useToast()
  const list = useShopping()
  const cats = useCategories()
  const sugg = useQuery({ queryKey: keys.suggestions, queryFn: () => get<InventoryItem[] | Product[]>('/shopping/suggestions') })
  const [text, setText] = useState('')
  const dtext = useDebounced(text, 200)
  const matches = useQuery({
    queryKey: ['products', { q: dtext, ac: true }],
    queryFn: () => get<Product[]>(`/products${qs({ q: dtext, limit: 6 })}`),
    enabled: dtext.trim().length >= 2,
  })

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.shopping })
    void qc.invalidateQueries({ queryKey: keys.suggestions })
    void qc.invalidateQueries({ queryKey: keys.dashboard })
  }
  const add = useMutation({
    mutationFn: (body: Record<string, unknown>) => post<ShoppingItem>('/shopping', body),
    onSuccess: () => {
      setText('')
      refresh()
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  const update = useMutation({
    mutationFn: ({ item, body }: { item: ShoppingItem; body: Record<string, unknown> }) =>
      patch<ShoppingItem>(
        `/shopping/${item.id}`,
        body,
        // check/uncheck is last-write-wins (contract §7.7): no If-Match; other edits keep optimistic concurrency.
        Object.keys(body).every((k) => k === 'checked') ? undefined : { headers: { 'If-Match': String(item.version) } },
      ),
    onMutate: async ({ item, body }) => {
      await qc.cancelQueries({ queryKey: keys.shopping })
      const prev = qc.getQueryData<ShoppingItem[]>(keys.shopping)
      qc.setQueryData<ShoppingItem[]>(keys.shopping, (old) => old?.map((i) => (i.id === item.id ? { ...i, ...body } : i)))
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      qc.setQueryData(keys.shopping, ctx?.prev)
      toast.push(t('common.saveFailed'), 'error')
    },
    onSettled: refresh,
  })
  const remove = useMutation({ mutationFn: (i: ShoppingItem) => del(`/shopping/${i.id}`), onSuccess: refresh })
  const clear = useMutation({ mutationFn: () => post('/shopping/clear-checked'), onSuccess: refresh })

  const items = list.data ?? []
  const [groupBy, setGroupByState] = useState<'category' | 'store'>(() => {
    try {
      return localStorage.getItem('pn.shopping.group') === 'store' ? 'store' : 'category'
    } catch {
      return 'category'
    }
  })
  const setGroupBy = (g: 'category' | 'store') => {
    setGroupByState(g)
    try {
      localStorage.setItem('pn.shopping.group', g)
    } catch {
      /* ignore */
    }
  }
  const [editing, setEditing] = useState<ShoppingItem | null>(null)
  const [putAway, setPutAway] = useState(false)
  const stores = [...new Set(items.map((i) => i.store).filter((s): s is string => !!s))].sort()
  const groups =
    groupBy === 'store'
      ? [...stores, null].map((st) => ({
          key: st ?? '',
          title: st ?? t('shopping.anyStore'),
          items: items.filter((i) => (i.store ?? null) === st).sort((a, b) => Number(a.checked) - Number(b.checked) || a.name.localeCompare(b.name)),
        })).filter((g) => g.items.length)
      : groupShopping(items, cats.data ?? []).map((g) => ({ key: g.key, title: g.category?.name ?? t('shopping.noCategory'), items: g.items }))
  const checkedCount = items.filter((i) => i.checked).length
  const productOf = (s: InventoryItem | Product): Product => ('product' in s ? s.product : s)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const name = text.trim()
    if (name) add.mutate({ name, quantity: 1 })
  }

  const copy = async () => {
    const out = shoppingToText(items, cats.data ?? [], t('shopping.noCategory'), (u) => t(`units.${u}`))
    try {
      await navigator.clipboard.writeText(out)
      toast.push(t('shopping.copied'), 'success')
    } catch {
      toast.push(t('shopping.copyFailed'), 'error')
    }
  }

  return (
    <>
      <PageHeader
        title={t('nav.shopping')}
        actions={
          <>
            <Button onClick={() => void copy()} disabled={!items.length}>
              <ClipboardCopy className="size-4" /> {t('shopping.copy')}
            </Button>
            <a href="/api/export/shopping.csv" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-surface px-4 text-sm font-semibold ring-1 ring-cream-200 hover:bg-cream-200">
              <Download className="size-4" /> CSV
            </a>
            <a href="/api/export/shopping.json" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-surface px-4 text-sm font-semibold ring-1 ring-cream-200 hover:bg-cream-200">
              <Download className="size-4" /> JSON
            </a>
          </>
        }
      />

      <form onSubmit={submit} className="relative mb-5">
        <div className="flex gap-2">
          <Input
            aria-label={t('shopping.addPlaceholder')}
            placeholder={t('shopping.addPlaceholder')}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="min-h-12 flex-1 rounded-2xl border-0 shadow-card"
            autoComplete="off"
          />
          <Button type="submit" variant="primary" className="min-h-12 rounded-2xl" disabled={!text.trim()} loading={add.isPending}>
            <Plus className="size-5" /> {t('common.add')}
          </Button>
        </div>
        {text.trim().length >= 2 && !!matches.data?.length && (
          <ul role="listbox" className="absolute inset-x-0 top-14 z-20 overflow-hidden rounded-2xl bg-surface shadow-xl ring-1 ring-cream-200">
            {matches.data.map((p) => (
              <li key={p.id} role="option" aria-selected={false}>
                <button
                  type="button"
                  className="flex min-h-12 w-full items-center gap-2 px-4 text-left hover:bg-cream-100"
                  onClick={() =>
                    add.mutate({ product_id: p.id, name: p.name, quantity: 1, category_id: p.category_id })
                  }
                >
                  <ShoppingBasket className="size-4 text-leaf-600" />
                  <span className="font-medium">{p.name}</span>
                  {p.brand && <span className="text-xs text-ink-500">{p.brand}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </form>

      {!!sugg.data?.length && (
        <Card className="mb-5 bg-honey-50">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-bold text-honey-600">
            <Lightbulb className="size-4" /> {t('shopping.suggestions')}
          </h2>
          <div className="flex flex-wrap gap-2">
            {sugg.data.map((s) => {
              const p = productOf(s)
              return (
                <button
                  key={p.id}
                  onClick={() => add.mutate({ product_id: p.id, name: p.name, quantity: 1, category_id: p.category_id })}
                  className="inline-flex min-h-10 items-center gap-1.5 rounded-full bg-surface px-4 text-sm font-medium shadow-sm hover:bg-leaf-50"
                >
                  <Plus className="size-4 text-leaf-600" /> {p.name}
                </button>
              )
            })}
          </div>
        </Card>
      )}

      {items.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-sm text-ink-500">{t('shopping.groupBy')}</span>
          <Chip active={groupBy === 'category'} onClick={() => setGroupBy('category')}>
            {t('shopping.byCategory')}
          </Chip>
          <Chip active={groupBy === 'store'} onClick={() => setGroupBy('store')}>
            <Store className="mr-1 inline size-4" />
            {t('shopping.byStore')}
          </Chip>
        </div>
      )}
      {editing && (
        <EditItem
          item={editing}
          stores={stores}
          onClose={() => setEditing(null)}
          onSave={(body) => {
            update.mutate({ item: editing, body })
            setEditing(null)
          }}
        />
      )}
      {putAway && <PutAway items={items.filter((i) => i.checked)} onClose={() => setPutAway(false)} onDone={() => clear.mutate()} />}
      {list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.isLoading ? (
        <ListSkeleton rows={4} />
      ) : items.length === 0 ? (
        <EmptyState icon={<ShoppingBasket className="size-8" />} title={t('shopping.empty')} hint={t('shopping.emptyHint')} />
      ) : (
        <div className="space-y-4">
          {groups.map((g) => (
            <Card key={g.key || 'none'} className="py-3">
              <h2 className="text-xs font-bold uppercase tracking-wide text-ink-500">{g.title}</h2>
              <ul className="divide-y divide-cream-200">
                {g.items.map((i) => (
                  <ShoppingRow
                    key={i.id}
                    item={i}
                    onToggle={(it) => update.mutate({ item: it, body: { checked: !it.checked } })}
                    onQty={(it, q) => update.mutate({ item: it, body: { quantity: q } })}
                    onDelete={(it) => remove.mutate(it)}
                    onEdit={setEditing}
                  />
                ))}
              </ul>
            </Card>
          ))}
          {checkedCount > 0 && (
            <div className="grid gap-2 sm:grid-cols-2">
              <Button variant="primary" onClick={() => setPutAway(true)} data-testid="put-away">
                <PackageCheck className="size-4" /> {t('shopping.putAway', { count: checkedCount })}
              </Button>
              <Button loading={clear.isPending} onClick={() => clear.mutate()}>
                <Trash2 className="size-4" /> {t('shopping.clearChecked', { count: checkedCount })}
              </Button>
            </div>
          )}
        </div>
      )}
    </>
  )
}

function EditItem({
  item,
  stores,
  onClose,
  onSave,
}: {
  item: ShoppingItem
  stores: string[]
  onClose: () => void
  onSave: (body: Record<string, unknown>) => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(item.name)
  const [note, setNote] = useState(item.note ?? '')
  const [store, setStore] = useState(item.store ?? '')
  return (
    <Modal
      open
      onClose={onClose}
      title={t('shopping.editTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" disabled={!name.trim()} onClick={() => onSave({ name: name.trim(), note: note.trim() || null, store: store.trim() || null })}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label={t('shopping.name')}>{(id) => <Input id={id} value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label={t('shopping.store')} hint={t('shopping.storeHint')}>
          {(id) => (
            <>
              <Input id={id} list="pn-stores" value={store} maxLength={60} onChange={(e) => setStore(e.target.value)} placeholder="Netto, Rema 1000…" />
              <datalist id="pn-stores">
                {stores.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </>
          )}
        </Field>
        <Field label={t('shopping.note')}>{(id) => <Input id={id} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />}</Field>
      </div>
    </Modal>
  )
}

/** After shopping: put the ticked items into stock in one go (each its own undoable stock op). */
function PutAway({ items, onClose, onDone }: { items: ShoppingItem[]; onClose: () => void; onDone: () => void }) {
  const { t, i18n } = useTranslation()
  const toast = useToast()
  const invalidate = useInvalidateStock()
  const linked = items.filter((i) => i.product_id)
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries(linked.map((i) => [i.id, String(i.quantity)])))
  const [busy, setBusy] = useState(false)
  const go = async () => {
    setBusy(true)
    let n = 0
    try {
      for (const i of linked) {
        const q = Number((qty[i.id] ?? '').replace(',', '.'))
        if (!(q > 0)) continue
        await enqueueOp({ type: 'add', product_id: i.product_id, quantity: q })
        n++
      }
      void invalidate()
      onDone()
      onClose()
      toast.push(t('shopping.putAwayDone', { count: n }), 'success')
    } catch {
      toast.push(t('inventory.changeFailed'), 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal
      open
      onClose={onClose}
      title={t('shopping.putAwayTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={busy} onClick={() => void go()} data-testid="put-away-confirm">
            {t('shopping.putAwayConfirm')}
          </Button>
        </>
      }
    >
      <p className="mb-2 text-sm text-ink-500">{t('shopping.putAwayHint')}</p>
      <ul className="divide-y divide-cream-200">
        {items.map((i) => (
          <li key={i.id} className="flex items-center gap-3 py-2">
            <span className="min-w-0 flex-1 truncate">{i.name}</span>
            {i.product_id ? (
              <>
                <Input className="w-20! text-right" inputMode="decimal" aria-label={t('recipes.amountFor', { name: i.name })} value={qty[i.id] ?? ''} onChange={(e) => setQty({ ...qty, [i.id]: e.target.value })} />
                <span className="w-10 text-sm text-ink-500">{i.unit ? t(`units.${i.unit}`) : ''}</span>
              </>
            ) : (
              <span className="text-xs text-ink-500">{t('shopping.notLinked', { lng: i18n.language })}</span>
            )}
          </li>
        ))}
      </ul>
    </Modal>
  )
}
