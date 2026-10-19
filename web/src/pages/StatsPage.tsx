import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { get } from '../api/client'
import { keys } from '../api/queries'
import type { StatsResponse } from '../api/types'
import { Card, ErrorState, PageHeader, Skeleton, Tabs } from '../components/ui'
import { formatQty } from '../lib/format'

export function DailyBars({ daily, label }: { daily: StatsResponse['daily']; label: string }) {
  const { t } = useTranslation()
  const max = Math.max(1, ...daily.flatMap((d) => [d.added, d.removed]))
  const w = 100 / Math.max(1, daily.length)
  return (
    <figure>
      <svg viewBox="0 0 100 40" className="h-48 w-full" role="img" aria-label={label} preserveAspectRatio="none">
        {daily.map((d, i) => {
          const ah = (d.added / max) * 36
          const rh = (d.removed / max) * 36
          return (
            <g key={d.date}>
              <title>{`${d.date}: +${d.added} / -${d.removed}`}</title>
              <rect x={i * w + w * 0.1} y={38 - ah} width={w * 0.38} height={ah} rx={0.4} className="fill-leaf-500" />
              <rect x={i * w + w * 0.52} y={38 - rh} width={w * 0.38} height={rh} rx={0.4} className="fill-tomato-500" />
            </g>
          )
        })}
        <line x1="0" x2="100" y1="38" y2="38" className="stroke-ink-300" strokeWidth="0.3" />
      </svg>
      <figcaption className="mt-2 flex gap-4 text-xs text-ink-500">
        <span className="flex items-center gap-1"><span className="size-2.5 rounded-sm bg-leaf-500" />{t('stats.added')}</span>
        <span className="flex items-center gap-1"><span className="size-2.5 rounded-sm bg-tomato-500" />{t('stats.removed')}</span>
      </figcaption>
    </figure>
  )
}

function Top({ title, rows }: { title: string; rows: StatsResponse['top_added'] }) {
  const { t, i18n } = useTranslation()
  const max = Math.max(1, ...rows.map((r) => r.quantity))
  return (
    <Card>
      <h2 className="mb-3 text-lg font-bold">{title}</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-ink-500">{t('stats.none')}</p>
      ) : (
        <ol className="space-y-2">
          {rows.slice(0, 8).map((r) => (
            <li key={r.product_id} className="text-sm">
              <div className="flex justify-between">
                <span className="truncate font-medium">{r.name}</span>
                <span className="tabular-nums">{formatQty(r.quantity, i18n.language)}</span>
              </div>
              <div className="mt-1 h-2 rounded-full bg-cream-200">
                <div className="h-2 rounded-full bg-leaf-500" style={{ width: `${(r.quantity / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}

export default function StatsPage() {
  const { t } = useTranslation()
  const [days, setDays] = useState('30')
  const q = useQuery({ queryKey: keys.stats(Number(days)), queryFn: () => get<StatsResponse>(`/stats?days=${days}`) })
  return (
    <>
      <PageHeader title={t('nav.stats')} />
      <Tabs
        tabs={[
          { id: '7', label: t('stats.days', { count: 7 }) },
          { id: '30', label: t('stats.days', { count: 30 }) },
          { id: '90', label: t('stats.days', { count: 90 }) },
        ]}
        value={days}
        onChange={setDays}
      />
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : !q.data ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="space-y-4">
          <Card>
            <h2 className="mb-3 text-lg font-bold">{t('stats.daily')}</h2>
            <DailyBars daily={q.data.daily ?? []} label={t('stats.daily')} />
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Top title={t('stats.mostAdded')} rows={q.data.top_added ?? []} />
            <Top title={t('stats.mostConsumed')} rows={q.data.top_consumed ?? []} />
          </div>
        </div>
      )}
    </>
  )
}
