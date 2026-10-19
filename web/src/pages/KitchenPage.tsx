// /kitchen – a calm, glanceable screen for a kitchen tablet: big actions, what to use first, and
// one-tap "took one" tiles for the products the household uses most. Every tap is undoable.
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { CalendarClock, Home, Minus, Moon, PackagePlus, PackageMinus, ShoppingBasket, Star, Sun, TrendingDown, Undo2 } from 'lucide-react'
import { get, put } from '../api/client'
import { useDashboard, useInvalidateStock } from '../api/queries'
import type { InventoryItem, Product } from '../api/types'
import { ProductThumb } from '../components/ProductThumb'
import { ErrorState, Skeleton } from '../components/ui'
import { enqueueOp, getStore } from '../offline'
import { cn, formatQty } from '../lib/format'
import { saveMode } from '../scan/mode'
import { WakeLock } from '../scan/wakelock'

interface Tile extends InventoryItem {
  uses: number
}
interface Taken {
  opId: string
  product: Product
  qty: number
  id: number
}

const DIM_KEY = 'pn.kitchen.dim'

export default function KitchenPage() {
  const { t, i18n } = useTranslation()
  const nav = useNavigate()
  const qc = useQueryClient()
  const invalidate = useInvalidateStock()
  const dash = useDashboard()
  const tiles = useQuery({ queryKey: ['kitchen', 'tiles'], queryFn: () => get<Tile[]>('/kitchen/tiles?limit=12'), refetchInterval: 60_000 })
  // optimistic stock changes until the server's numbers come back
  const [pending, setPending] = useState<{ at: number; by: Record<string, number> }>({ at: 0, by: {} })
  const offsets = pending.at === tiles.dataUpdatedAt ? pending.by : {}
  const [taken, setTaken] = useState<Taken | null>(null)
  const [editing, setEditing] = useState(false)
  const [now, setNow] = useState(() => new Date())
  const [dim, setDim] = useState(() => {
    try {
      return localStorage.getItem(DIM_KEY) === '1'
    } catch {
      return false
    }
  })
  const takenN = useRef(0)

  useEffect(() => {
    const iv = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(iv)
  }, [])
  useEffect(() => {
    // stay on while the kitchen screen is open (best effort; not every browser supports it)
    const wl = new WakeLock()
    void wl.acquire()
    return () => void wl.release()
  }, [])
  useEffect(() => {
    const off = getStore().subscribeData(() => {
      void qc.invalidateQueries({ queryKey: ['kitchen'] })
      void invalidate()
    })
    return () => void off()
  }, [qc, invalidate])
  useEffect(() => {
    if (!taken) return
    const id = taken.id
    const tm = setTimeout(() => setTaken((x) => (x?.id === id ? null : x)), 8000)
    return () => clearTimeout(tm)
  }, [taken])

  // fresh server numbers (dataUpdatedAt changes) already include the change: offsets reset
  const bump = (pid: string, d: number) =>
    setPending((o) => {
      const by = o.at === tiles.dataUpdatedAt ? o.by : {}
      return { at: tiles.dataUpdatedAt, by: { ...by, [pid]: (by[pid] ?? 0) + d } }
    })

  const take = async (tile: Tile) => {
    const p = tile.product
    try {
      const op = await enqueueOp({ type: 'remove', product_id: p.id, quantity: 1 })
      bump(p.id, -1)
      navigator.vibrate?.(30)
      setTaken({ opId: op.client_op_id, product: p, qty: 1, id: ++takenN.current })
    } catch {
      setTaken(null)
    }
  }
  const undo = async () => {
    if (!taken) return
    const x = taken
    setTaken(null)
    await enqueueOp({ type: 'undo', undoes_client_op_id: x.opId, product_id: x.product.id, quantity: x.qty })
    bump(x.product.id, x.qty)
  }
  const toggleFav = async (p: Product) => {
    await put<Product>(`/products/${p.id}/favorite`, { favorite: !p.favorite })
    await qc.invalidateQueries({ queryKey: ['kitchen', 'tiles'] })
  }
  const scan = (mode: 'add' | 'remove') => {
    saveMode(mode)
    nav('/scan')
  }
  const setDimmed = (v: boolean) => {
    setDim(v)
    try {
      localStorage.setItem(DIM_KEY, v ? '1' : '0')
    } catch {
      /* ignore */
    }
  }

  const d = dash.data
  const useFirst = d ? [...d.expired, ...d.expiring_soon].slice(0, 6) : []
  const hour = now.getHours()
  const greet = hour < 10 ? 'morning' : hour < 17 ? 'day' : 'evening'

  return (
    <div className={cn('min-h-dvh bg-cream-50 text-ink-900 transition-[filter] duration-500', dim && 'brightness-[.55]')} data-testid="kitchen">
      <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 sm:p-6">
        <header className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-[clamp(2.5rem,7vw,4.5rem)] font-semibold leading-none tracking-[-0.04em] tabular-nums">
              {now.toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' })}
            </div>
            <div className="mt-1 text-ink-500">
              {t(`kitchen.greet_${greet}`)} · {now.toLocaleDateString(i18n.language, { weekday: 'long', day: 'numeric', month: 'long' })}
            </div>
          </div>
          <button type="button" onClick={() => setDimmed(!dim)} aria-label={t(dim ? 'kitchen.bright' : 'kitchen.dim')} className="grid size-12 place-items-center rounded-2xl bg-surface ring-1 ring-cream-200">
            {dim ? <Sun className="size-5" /> : <Moon className="size-5" />}
          </button>
          <Link to="/" aria-label={t('nav.home')} className="grid size-12 place-items-center rounded-2xl bg-surface ring-1 ring-cream-200">
            <Home className="size-5" />
          </Link>
        </header>

        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Action onClick={() => scan('add')} icon={PackagePlus} label={t('kitchen.scanIn')} tone="bg-leaf-600 text-white" testid="kitchen-scan-in" />
          <Action onClick={() => scan('remove')} icon={PackageMinus} label={t('kitchen.scanOut')} tone="bg-[#c8432b] text-white" testid="kitchen-scan-out" />
          <Action to="/shopping" icon={ShoppingBasket} label={t('kitchen.shopping')} count={d?.shopping_open_count} tone="bg-surface ring-1 ring-cream-200" />
          <Action to="/expiring" icon={CalendarClock} label={t('kitchen.expiring')} count={d ? d.expired.length + d.expiring_soon.length : undefined} tone="bg-surface ring-1 ring-cream-200" />
        </section>

        <section>
          <div className="mb-2 flex items-baseline justify-between">
            <h2 className="text-lg font-semibold">{t('kitchen.quick')}</h2>
            <button type="button" className="text-sm font-semibold text-leaf-600" onClick={() => setEditing((e) => !e)} data-testid="kitchen-edit">
              {editing ? t('common.done') : t('kitchen.editFavorites')}
            </button>
          </div>
          {tiles.isError ? (
            <ErrorState error={tiles.error} onRetry={() => void tiles.refetch()} />
          ) : !tiles.data ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {Array.from({ length: 8 }, (_, i) => (
                <Skeleton key={i} className="h-36 rounded-3xl" />
              ))}
            </div>
          ) : tiles.data.length === 0 ? (
            <p className="rounded-3xl bg-surface p-6 text-ink-500 ring-1 ring-cream-200">{t('kitchen.noTiles')}</p>
          ) : (
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" data-testid="kitchen-tiles">
              {tiles.data.map((tile) => {
                const qty = Math.max(0, tile.total_quantity + (offsets[tile.product.id] ?? 0))
                const p = tile.product
                return (
                  <li key={p.id} className="relative">
                    <button
                      type="button"
                      disabled={!editing && qty <= 0}
                      onClick={() => (editing ? void toggleFav(p) : void take(tile))}
                      aria-label={editing ? t('kitchen.toggleFavorite', { name: p.name }) : t('kitchen.takeOne', { name: p.name })}
                      className={cn(
                        'flex h-full min-h-36 w-full flex-col gap-2 rounded-3xl bg-surface p-3 text-left shadow-card ring-1 ring-cream-200/70 transition active:scale-[.97] disabled:opacity-50',
                        editing && 'ring-2 ring-leaf-500/50',
                      )}
                      data-testid="kitchen-tile"
                    >
                      <div className="flex items-start gap-3">
                        <ProductThumb name={p.name} src={p.image_url} className="size-14" />
                        <div className="min-w-0 flex-1">
                          <div className="line-clamp-2 font-semibold leading-tight">{p.name}</div>
                          <div className={cn('mt-0.5 text-sm tabular-nums', tile.low_stock || qty <= 0 ? 'text-tomato-600' : 'text-ink-500')} data-testid="kitchen-qty">
                            {formatQty(qty)} {t('kitchen.left')}
                          </div>
                        </div>
                      </div>
                      <div className="mt-auto flex items-center justify-between">
                        {p.favorite ? <Star className="size-5 fill-honey-400 text-honey-400" aria-label={t('kitchen.favorite')} /> : <span />}
                        {editing ? (
                          <span className="text-sm font-semibold text-leaf-600">{p.favorite ? t('kitchen.unpin') : t('kitchen.pin')}</span>
                        ) : (
                          <span className="flex items-center gap-1 rounded-2xl bg-[#c8432b] px-4 py-2 text-lg font-bold text-white">
                            <Minus className="size-5" strokeWidth={3} />1
                          </span>
                        )}
                      </div>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <div className="grid gap-5 lg:grid-cols-2">
          <ListSection title={t('kitchen.useFirst')} icon={CalendarClock} loading={!d} empty={t('kitchen.nothingExpiring')} items={useFirst} kind="expiry" />
          <ListSection title={t('kitchen.lowStock')} icon={TrendingDown} loading={!d} empty={t('kitchen.nothingLow')} items={d?.low_stock.slice(0, 6) ?? []} kind="qty" />
        </div>
      </div>

      {taken && (
        <div className="fixed inset-x-0 bottom-0 z-40 flex justify-center p-4" role="status">
          <div className="flex w-full max-w-xl items-center gap-3 rounded-3xl bg-[#1c2420] p-3 pl-5 text-white shadow-2xl ring-1 ring-white/15">
            <span className="min-w-0 flex-1 truncate text-lg">{t('kitchen.took', { name: taken.product.name })}</span>
            <button type="button" onClick={() => void undo()} className="flex items-center gap-2 rounded-2xl bg-white px-4 py-3 font-bold text-[#111]" data-testid="kitchen-undo">
              <Undo2 className="size-5" /> {t('kitchen.undo')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function Action({
  icon: Icon,
  label,
  tone,
  to,
  onClick,
  count,
  testid,
}: {
  icon: typeof Home
  label: string
  tone: string
  to?: string
  onClick?: () => void
  count?: number
  testid?: string
}) {
  const body = (
    <>
      <Icon className="size-8" />
      <span className="text-lg font-semibold leading-tight">{label}</span>
      {count !== undefined && <span className="absolute right-4 top-3 text-2xl font-semibold tabular-nums">{count}</span>}
    </>
  )
  const cls = cn('relative flex min-h-28 flex-col justify-between rounded-3xl p-4 text-left shadow-card transition active:scale-[.97]', tone)
  return to ? (
    <Link to={to} className={cls}>
      {body}
    </Link>
  ) : (
    <button type="button" onClick={onClick} className={cls} data-testid={testid}>
      {body}
    </button>
  )
}

function ListSection({
  title,
  icon: Icon,
  items,
  empty,
  loading,
  kind,
}: {
  title: string
  icon: typeof Home
  items: InventoryItem[]
  empty: string
  loading: boolean
  kind: 'expiry' | 'qty'
}) {
  const { i18n } = useTranslation()
  return (
    <section className="rounded-3xl bg-surface p-4 ring-1 ring-cream-200">
      <h2 className="mb-2 flex items-center gap-2 text-lg font-semibold">
        <Icon className="size-5 text-ink-500" /> {title}
      </h2>
      {loading ? (
        <Skeleton className="h-24" />
      ) : items.length === 0 ? (
        <p className="py-3 text-ink-500">{empty}</p>
      ) : (
        <ul className="divide-y divide-cream-200">
          {items.map((it) => (
            <li key={it.product.id}>
              <Link to={`/products/${it.product.id}`} className="flex min-h-14 items-center gap-3 py-2">
                <ProductThumb name={it.product.name} src={it.product.image_url} className="size-10 text-base" />
                <span className="min-w-0 flex-1 truncate font-medium">{it.product.name}</span>
                <span className="text-sm tabular-nums text-ink-500">
                  {kind === 'expiry' && it.next_expiry
                    ? new Date(it.next_expiry).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short' })
                    : formatQty(it.total_quantity)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
