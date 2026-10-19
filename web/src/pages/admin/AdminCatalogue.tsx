import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { get } from '../../api/client'
import type { CatalogueStatus } from '../../api/types'
import { Card, ErrorState, Skeleton } from '../../components/ui'

function KV({ data }: { data?: Record<string, unknown> }) {
  const entries = Object.entries(data ?? {})
  if (!entries.length) return <p className="text-sm text-ink-500">—</p>
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
      {entries.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-2 border-b border-cream-100 py-1">
          <dt className="text-ink-500">{k.replace(/_/g, ' ')}</dt>
          <dd className="font-semibold tabular-nums">
            {typeof v === 'number' && k.includes('rate') ? `${Math.round(v * 100)}%` : String(v ?? '—')}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export default function AdminCatalogue() {
  const { t } = useTranslation()
  const q = useQuery({ queryKey: ['admin', 'catalogue'], queryFn: () => get<CatalogueStatus>('/admin/catalogue') })
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <Skeleton className="h-64" />
  const d = q.data
  return (
    <div className="space-y-4">
      <Card>
        <h2 className="mb-2 text-lg font-bold">{t('admin.byStatus')}</h2>
        <KV data={d.by_status ?? d.counts} />
      </Card>
      {d.by_source && (
        <Card>
          <h2 className="mb-2 text-lg font-bold">{t('admin.bySource')}</h2>
          <KV data={d.by_source} />
        </Card>
      )}
      <Card>
        <h2 className="mb-2 text-lg font-bold">{t('admin.lookupStats')}</h2>
        <KV data={d.lookup_stats ?? {}} />
      </Card>
      <Card>
        <h2 className="mb-2 text-lg font-bold">{t('admin.failedLookups')}</h2>
        {d.failed_lookups?.length ? (
          <ul className="divide-y divide-cream-100 text-sm">
            {d.failed_lookups.map((f, i) => (
              <li key={i} className="flex justify-between gap-2 py-2">
                <span className="font-mono">{f.barcode ?? f.raw}</span>
                <span className="text-ink-500">{f.provider ?? f.status}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-500">{t('admin.none')}</p>
        )}
      </Card>
      <Card>
        <h2 className="mb-2 text-lg font-bold">{t('admin.duplicates')}</h2>
        {d.duplicate_candidates?.length ? (
          <ul className="divide-y divide-cream-100 text-sm">
            {d.duplicate_candidates.map((c, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2 py-2">
                {c.a && c.b ? (
                  <>
                    <Link className="font-semibold text-leaf-700" to={`/products/${c.a.id}`}>{c.a.name}</Link>
                    <span className="text-ink-500">≈</span>
                    <Link className="font-semibold text-leaf-700" to={`/products/${c.b.id}`}>{c.b.name}</Link>
                  </>
                ) : (
                  <span>{c.names?.join(' ≈ ')}</span>
                )}
                {c.reason && <span className="text-xs text-ink-500">({c.reason})</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-500">{t('admin.none')}</p>
        )}
      </Card>
    </div>
  )
}
