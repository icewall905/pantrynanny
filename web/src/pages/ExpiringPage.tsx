import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { CalendarCheck } from 'lucide-react'
import { useDashboard } from '../api/queries'
import type { InventoryItem } from '../api/types'
import { ExpiryBadge } from '../components/ExpiryBadge'
import { ProductThumb } from '../components/ProductThumb'
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from '../components/ui'
import { formatQty } from '../lib/format'

function Section({ title, items }: { title: string; items: InventoryItem[] }) {
  const { i18n } = useTranslation()
  if (!items.length) return null
  const sorted = [...items].sort((a, b) => (a.next_expiry ?? '9').localeCompare(b.next_expiry ?? '9'))
  return (
    <section className="mb-6">
      <h2 className="mb-2 text-lg font-bold">
        {title} <span className="text-ink-500">({items.length})</span>
      </h2>
      <ul className="space-y-2">
        {sorted.map((i) => (
          <li key={i.product.id}>
            <Link to={`/products/${i.product.id}`} className="flex items-center gap-3 rounded-[var(--radius-card)] bg-white p-3 shadow-card">
              <ProductThumb name={i.product.name} src={i.product.image_url} />
              <div className="min-w-0 flex-1">
                <div className="truncate font-semibold">{i.product.name}</div>
                <div className="text-xs text-ink-500">{formatQty(i.total_quantity, i18n.language)}</div>
              </div>
              <ExpiryBadge date={i.next_expiry} />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function ExpiringPage() {
  const { t } = useTranslation()
  const q = useDashboard()
  const d = q.data
  return (
    <>
      <PageHeader title={t('nav.expiring')} subtitle={t('expiring.subtitle')} />
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : !d ? (
        <ListSkeleton />
      ) : d.expired.length + d.expiring_soon.length === 0 ? (
        <EmptyState icon={<CalendarCheck className="size-8" />} title={t('expiring.none')} hint={t('expiring.noneHint')} />
      ) : (
        <>
          <Section title={t('expiring.expired')} items={d.expired} />
          <Section title={t('expiring.useFirst')} items={d.expiring_soon} />
        </>
      )}
    </>
  )
}
