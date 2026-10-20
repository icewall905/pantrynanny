import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  AlertOctagon,
  CalendarClock,
  HelpCircle,
  PackageCheck,
  ScanBarcode,
  ShoppingBasket,
  TrendingDown,
  type LucideIcon,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import { useDashboard } from '../api/queries'
import type { Transaction } from '../api/types'
import { useAuth } from '../auth/AuthProvider'
import { ProductThumb } from '../components/ProductThumb'
import { Card, ErrorState, Skeleton } from '../components/ui'
import { cn, formatDateTime, formatQty } from '../lib/format'

function Stat({
  to,
  icon: Icon,
  value,
  label,
  tone,
}: {
  to: string
  icon: LucideIcon
  value: number
  label: string
  tone: string
}) {
  return (
    <Link
      to={to}
      className="group rounded-[var(--radius-card)] bg-surface p-4 shadow-card ring-1 ring-cream-200/70 transition hover:-translate-y-0.5 hover:ring-leaf-500/40"
    >
      <div className={cn('mb-3 grid size-9 place-items-center rounded-xl sm:mb-4 sm:size-10', tone)}>
        <Icon className="size-5" />
      </div>
      <div className="text-[1.75rem] font-semibold leading-none tracking-[-0.03em] tabular-nums sm:text-[2rem]">{value}</div>
      <div className="mt-1.5 text-sm text-ink-500">{label}</div>
    </Link>
  )
}

function TxnList({ items, empty }: { items: Transaction[]; empty: string }) {
  const { i18n } = useTranslation()
  if (!items.length) return <p className="py-4 text-sm text-ink-500">{empty}</p>
  return (
    <ul className="divide-y divide-cream-200">
      {items.slice(0, 6).map((tx) => (
        <li key={tx.id}>
          <Link to={`/products/${tx.product_id}`} className="flex min-h-14 items-center gap-3 py-2">
            <ProductThumb name={tx.product?.name ?? '?'} src={tx.product?.image_url} className="size-10 text-base" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold">{tx.product?.name ?? '—'}</div>
              <div className="text-xs text-ink-500">{formatDateTime(tx.occurred_at, i18n.language)}</div>
            </div>
            <span className="text-sm font-bold tabular-nums">
              {tx.quantity_delta > 0 ? '+' : ''}
              {formatQty(tx.quantity_delta, i18n.language)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

export default function DashboardPage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const q = useDashboard()
  const d = q.data

  return (
    <>
      <div className="relative mb-6 flex flex-wrap items-center justify-between gap-4 overflow-hidden rounded-[1.75rem] bg-gradient-to-br from-leaf-600 to-leaf-800 p-6 text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.15),0_20px_40px_-24px_var(--color-leaf-600)] sm:p-8">
        {/* soft light blobs for depth */}
        <div aria-hidden className="pointer-events-none absolute -right-16 -top-24 size-72 rounded-full bg-white/15 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute -bottom-28 left-1/3 size-64 rounded-full bg-leaf-500/40 blur-3xl" />
        <div className="relative">
          <p className="text-sm font-medium text-white/75">{t('dashboard.hello', { name: me?.user?.display_name })}</p>
          <h1 className="mt-1 text-2xl font-bold tracking-[-0.03em] sm:text-[2.25rem] sm:leading-tight">
            {d ? t('dashboard.inStock', { count: d.totals.products_in_stock }) : t('dashboard.title')}
          </h1>
        </div>
        <Link
          to="/scan"
          className="relative inline-flex min-h-14 items-center gap-2 rounded-2xl bg-white px-6 text-base font-semibold text-leaf-800 shadow-[0_10px_30px_-12px_rgb(0_0_0/0.45)] transition hover:scale-[1.02] active:scale-[0.98]"
        >
          <ScanBarcode className="size-6" /> {t('nav.scan')}
        </Link>
      </div>

      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.isLoading && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      )}
      {d && (
        <div className="space-y-6">
          {d.unknown_count > 0 && (
            <Link
              to="/unknown"
              data-testid="unknown-nudge"
              className="flex items-center gap-3 rounded-[var(--radius-card)] bg-honey-50 p-4 text-sm ring-1 ring-honey-400/50 transition hover:ring-honey-400"
            >
              <HelpCircle className="size-5 shrink-0 text-honey-600" />
              <span className="min-w-0 flex-1">{t('dashboard.unknownNudge', { count: d.unknown_count })}</span>
              <span className="font-semibold text-honey-600">{t('dashboard.unknownNudgeAction')}</span>
            </Link>
          )}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <Stat to="/inventory" icon={PackageCheck} value={d.totals.products_in_stock} label={t('dashboard.products')} tone="bg-leaf-100 text-leaf-700" />
            <Stat to="/inventory?low=1" icon={TrendingDown} value={d.low_stock.length} label={t('dashboard.low')} tone="bg-honey-50 text-honey-600" />
            <Stat to="/expiring" icon={CalendarClock} value={d.expiring_soon.length} label={t('dashboard.expiringSoon')} tone="bg-honey-50 text-honey-600" />
            <Stat to="/expiring" icon={AlertOctagon} value={d.expired.length} label={t('dashboard.expired')} tone="bg-tomato-100 text-tomato-600" />
            <Stat to="/unknown" icon={HelpCircle} value={d.unknown_count} label={t('dashboard.unknown')} tone="bg-sky-500/10 text-sky-500" />
            <Stat to="/shopping" icon={ShoppingBasket} value={d.shopping_open_count} label={t('dashboard.shopping')} tone="bg-leaf-100 text-leaf-700" />
          </div>

          <section aria-labelledby="by-loc">
            <h2 id="by-loc" className="mb-3 text-lg font-bold">
              {t('dashboard.byLocation')}
            </h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {d.by_location.map(({ location, item_count }) => (
                <Link
                  key={location.id}
                  to={`/inventory?location=${location.id}`}
                  className="rounded-[var(--radius-card)] bg-surface p-4 shadow-card ring-1 ring-cream-200/70 transition hover:-translate-y-0.5 hover:ring-leaf-500/40"
                >
                  <div className="truncate font-bold">{location.name}</div>
                  <div className="text-sm text-ink-500">{t('dashboard.items', { count: item_count })}</div>
                </Link>
              ))}
            </div>
          </section>

          <RunOutCard />

          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <h2 className="mb-1 text-lg font-bold">{t('dashboard.recentAdded')}</h2>
              <TxnList items={d.recently_added} empty={t('dashboard.nothingYet')} />
            </Card>
            <Card>
              <h2 className="mb-1 text-lg font-bold">{t('dashboard.recentConsumed')}</h2>
              <TxnList items={d.recently_consumed} empty={t('dashboard.nothingYet')} />
            </Card>
          </div>
        </div>
      )}
    </>
  )
}

interface RunOut {
  product_id: string
  name: string
  image_url: string | null
  total_quantity: number
  stock_unit: string
  days_left: number
  confidence: 'medium' | 'high'
}

/** "At your usual pace this runs out in ~N days": from the household's own history only. */
function RunOutCard() {
  const { t, i18n } = useTranslation()
  const q = useQuery({ queryKey: ['stats', 'runout'], queryFn: () => get<RunOut[]>('/stats/runout?days=10'), staleTime: 300_000 })
  if (!q.data?.length) return null
  return (
    <Card>
      <h2 className="mb-1 text-lg font-bold">{t('dashboard.runOut')}</h2>
      <p className="mb-1 text-xs text-ink-500">{t('dashboard.runOutHint')}</p>
      <ul className="divide-y divide-cream-200" data-testid="runout">
        {q.data.slice(0, 6).map((r) => (
          <li key={r.product_id}>
            <Link to={`/products/${r.product_id}`} className="flex min-h-14 items-center gap-3 py-2">
              <ProductThumb name={r.name} src={r.image_url} className="size-10 text-base" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">{r.name}</div>
                <div className="text-xs text-ink-500">
                  {t('dashboard.left', { qty: formatQty(r.total_quantity, i18n.language) })} · {t(`dashboard.conf_${r.confidence}`)}
                </div>
              </div>
              <span className="text-sm font-bold tabular-nums text-honey-600">{t('dashboard.inAboutDays', { count: Math.max(1, Math.round(r.days_left)) })}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}
