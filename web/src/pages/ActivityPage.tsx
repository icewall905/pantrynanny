import { Link } from 'react-router-dom'
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ArrowRightLeft, History, Minus, Plus, SlidersHorizontal, Undo2 } from 'lucide-react'
import { get, post } from '../api/client'
import type { Transaction } from '../api/types'
import { useInvalidateStock } from '../api/queries'
import { ProductThumb } from '../components/ProductThumb'
import { Button, EmptyState, ErrorState, ListSkeleton, PageHeader } from '../components/ui'
import { useToast } from '../components/Toast'
import { uuid } from '../offline'
import { cn, formatQty } from '../lib/format'

type Row = Transaction & { user_name: string | null; product: NonNullable<Transaction['product']> }
const PAGE = 50
const ICON = { add: Plus, remove: Minus, adjust: SlidersHorizontal, move: ArrowRightLeft, undo: Undo2 } as const

export default function ActivityPage() {
  const { t, i18n } = useTranslation()
  const toast = useToast()
  const qc = useQueryClient()
  const invalidate = useInvalidateStock()
  const q = useInfiniteQuery({
    queryKey: ['activity'],
    initialPageParam: '' as string,
    queryFn: ({ pageParam }) => get<Row[]>(`/activity?limit=${PAGE}${pageParam ? `&before=${encodeURIComponent(pageParam)}` : ''}`),
    getNextPageParam: (last) => (last.length === PAGE ? `${last[last.length - 1].created_at}|${last[last.length - 1].id}` : undefined),
  })
  const undo = useMutation({
    mutationFn: (r: Row) => post(`/transactions/${r.id}/undo`, { client_op_id: uuid() }),
    onSuccess: () => {
      toast.push(t('activity.undone'), 'success')
      void qc.invalidateQueries({ queryKey: ['activity'] })
      void invalidate()
    },
    onError: () => toast.push(t('activity.undoFailed'), 'error'),
  })
  const rows = q.data?.pages.flat() ?? []
  const days = new Map<string, Row[]>()
  for (const r of rows) {
    const k = new Date(r.occurred_at).toDateString()
    days.set(k, [...(days.get(k) ?? []), r])
  }

  return (
    <>
      <PageHeader title={t('activity.title')} subtitle={t('activity.subtitle')} />
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isLoading ? (
        <ListSkeleton rows={6} />
      ) : rows.length === 0 ? (
        <EmptyState icon={<History className="size-8" />} title={t('activity.empty')} />
      ) : (
        <div className="space-y-5" data-testid="activity">
          {[...days.entries()].map(([k, list]) => (
            <section key={k}>
              <h2 className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-500">
                {new Date(list[0].occurred_at).toLocaleDateString(i18n.language, { weekday: 'long', day: 'numeric', month: 'long' })}
              </h2>
              <ul className="divide-y divide-cream-200 rounded-[var(--radius-card)] bg-surface px-4 ring-1 ring-cream-200/70">
                {list.map((r) => {
                  const Icon = ICON[r.type] ?? History
                  const who = r.user_name ?? r.device_name ?? t('activity.someone')
                  return (
                    <li key={r.id} className={cn('flex min-h-14 items-center gap-3 py-2', r.undone && 'opacity-50')}>
                      <ProductThumb name={r.product.name} src={r.product.image_url} className="size-10 text-base" />
                      <div className="min-w-0 flex-1">
                        <Link to={`/products/${r.product_id}`} className={cn('block truncate font-semibold hover:underline', r.undone && 'line-through')}>
                          {r.product.name}
                        </Link>
                        <div className="truncate text-xs text-ink-500">
                          {new Date(r.occurred_at).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' })} · {t(`activity.type_${r.type}`)} · {who}
                          {r.reason === 'recipe' && ` · ${t('activity.fromRecipe')}`}
                          {r.undone && ` · ${t('activity.wasUndone')}`}
                        </div>
                      </div>
                      <span className={cn('flex items-center gap-1 text-sm font-bold tabular-nums', r.quantity_delta > 0 ? 'text-leaf-600' : r.quantity_delta < 0 ? 'text-tomato-600' : 'text-ink-500')}>
                        <Icon className="size-3.5" />
                        {formatQty(Math.abs(r.quantity_delta), i18n.language)}
                      </span>
                      {!r.undone && r.type !== 'undo' && (
                        <button
                          type="button"
                          aria-label={t('activity.undo', { name: r.product.name })}
                          onClick={() => window.confirm(t('activity.confirmUndo', { name: r.product.name })) && undo.mutate(r)}
                          className="grid size-10 place-items-center rounded-xl text-ink-500 hover:bg-cream-200/70"
                        >
                          <Undo2 className="size-4" />
                        </button>
                      )}
                    </li>
                  )
                })}
              </ul>
            </section>
          ))}
          {q.hasNextPage && (
            <Button className="w-full" loading={q.isFetchingNextPage} onClick={() => void q.fetchNextPage()}>
              {t('activity.more')}
            </Button>
          )}
        </div>
      )}
    </>
  )
}
