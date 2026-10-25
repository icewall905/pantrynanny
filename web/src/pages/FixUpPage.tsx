// Bulk "fix up stock": give many batches a location and/or expiry in a few taps
// (filter → select all → one action).
import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { CalendarClock, CheckSquare, FolderInput, Search, Square, Wand2, X } from 'lucide-react'
import { useInventory, useInvalidateStock, useLocations } from '../api/queries'
import { fixUpBatches } from '../api/stock'
import type { ISODate } from '../api/types'
import { ExpiryBadge } from '../components/ExpiryBadge'
import { useToast } from '../components/Toast'
import { Button, Chip, EmptyState, ErrorState, Input, ListSkeleton, PageHeader, Select } from '../components/ui'
import { chipDate, EXPIRY_PRESETS } from '../lib/expiry'
import { chunk, fixUpRows } from '../lib/fixUp'
import { cn, formatQty } from '../lib/format'
import { apiErrorText } from '../lib/opError'

type Action = { location_id: string } | { expires_at: ISODate | null }

export default function FixUpPage() {
  const { t, i18n } = useTranslation()
  const toast = useToast()
  const invalidate = useInvalidateStock()
  const inv = useInventory({ sort: 'name' })
  const locs = useLocations()
  const [noExpiry, setNoExpiry] = useState(true)
  const [locationId, setLocationId] = useState('')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [date, setDate] = useState('')

  const rows = useMemo(() => fixUpRows(inv.data ?? [], { noExpiry, locationId, q }), [inv.data, noExpiry, locationId, q])
  const locName = useMemo(() => new Map((locs.data ?? []).map((l) => [l.id, l.name])), [locs.data])
  // only what is still visible counts (a filter change never acts on hidden rows)
  const chosen = rows.filter((r) => selected.has(r.batch.id)).map((r) => r.batch.id)
  const allOn = rows.length > 0 && chosen.length === rows.length

  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  const toggleAll = () => setSelected(allOn ? new Set() : new Set(rows.map((r) => r.batch.id)))

  const apply = useMutation({
    mutationFn: async (a: Action) => {
      let changed = 0
      let unchanged = 0
      for (const ids of chunk(chosen)) {
        const r = await fixUpBatches({ batch_ids: ids, ...a })
        changed += r.changed
        unchanged += r.unchanged
      }
      return { changed, unchanged }
    },
    onSuccess: (r) => {
      setSelected(new Set())
      setDate('')
      toast.push(t('fixUp.done', { count: r.changed }), 'success')
    },
    onError: (e) => toast.push(apiErrorText(t, e, t('common.saveFailed')), 'error'),
    onSettled: () => void invalidate(),
  })
  const busy = apply.isPending || chosen.length === 0

  return (
    <>
      <PageHeader title={t('fixUp.title')} subtitle={t('fixUp.subtitle')} />
      <div className="sticky top-12 z-10 -mx-4 mb-3 space-y-2 bg-cream-100/95 px-4 pb-2 pt-1 backdrop-blur lg:top-0 lg:mx-0 lg:px-0">
        <div className="flex flex-wrap items-center gap-2">
          <Chip active={noExpiry} onClick={() => setNoExpiry((v) => !v)}>
            {t('fixUp.noExpiry')}
          </Chip>
          <Select aria-label={t('inventory.location')} className="w-auto!" value={locationId} onChange={(e) => setLocationId(e.target.value)}>
            <option value="">{t('inventory.allLocations')}</option>
            {locs.data?.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </Select>
          <div className="relative min-w-40 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-500" aria-hidden />
            <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('inventory.searchPlaceholder')} aria-label={t('inventory.search')} className="pl-9" />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={toggleAll} disabled={rows.length === 0} data-testid="fixup-select-all">
            {allOn ? <CheckSquare className="size-4" /> : <Square className="size-4" />}
            {allOn ? t('fixUp.selectNone') : t('fixUp.selectAll', { count: rows.length })}
          </Button>
          <span className="text-sm text-ink-500">{t('inventory.selected', { count: chosen.length })}</span>
        </div>

        {chosen.length > 0 && (
          <div className="pn-pop space-y-2 rounded-2xl bg-night p-3 text-white shadow-lg" data-testid="fixup-actions">
            <div className="flex items-center gap-2 overflow-x-auto [scrollbar-width:none] [&>*]:shrink-0">
              <FolderInput className="size-4 text-white/70" aria-label={t('fixUp.moveTo')} />
              {locs.data?.map((l) => (
                <Button key={l.id} size="sm" disabled={busy} onClick={() => apply.mutate({ location_id: l.id })}>
                  {l.name}
                </Button>
              ))}
            </div>
            <div className="flex items-center gap-2 overflow-x-auto [scrollbar-width:none] [&>*]:shrink-0">
              <CalendarClock className="size-4 text-white/70" aria-label={t('fixUp.setExpiry')} />
              {EXPIRY_PRESETS.map((c) => (
                <Button key={c.key} size="sm" disabled={busy} onClick={() => apply.mutate({ expires_at: chipDate(c) })} data-testid={`fixup-expiry-${c.key}`}>
                  {t(`scan.place.chip.${c.key}`)}
                </Button>
              ))}
              <input
                type="date"
                aria-label={t('inventory.expiryDate')}
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="min-h-9 rounded-xl bg-white px-2 text-sm text-ink-900"
              />
              <Button size="sm" variant="primary" disabled={busy || !date} onClick={() => apply.mutate({ expires_at: date })}>
                {t('fixUp.setDate')}
              </Button>
              <button aria-label={t('common.clear')} className="grid size-9 place-items-center rounded-lg hover:bg-white/10" onClick={() => setSelected(new Set())}>
                <X className="size-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {inv.isError ? (
        <ErrorState error={inv.error} onRetry={() => void inv.refetch()} />
      ) : inv.isLoading ? (
        <ListSkeleton />
      ) : rows.length === 0 ? (
        <EmptyState icon={<Wand2 className="size-8" />} title={t('fixUp.empty')} hint={t('fixUp.emptyHint')} />
      ) : (
        <ul className="divide-y divide-cream-100 rounded-[var(--radius-card)] bg-surface shadow-card ring-1 ring-cream-200/70">
          {rows.map(({ batch: b, product: p }) => (
            <li key={b.id}>
              <label className={cn('flex min-h-12 cursor-pointer items-center gap-3 px-3 py-2', selected.has(b.id) && 'bg-leaf-50')}>
                <input type="checkbox" checked={selected.has(b.id)} onChange={() => toggle(b.id)} className="size-5 shrink-0 accent-leaf-600" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{p.name}</span>
                  <span className="block truncate text-xs text-ink-500">
                    {[locName.get(b.location_id), `${formatQty(b.quantity, i18n.language)} ${p.stock_unit === 'pcs' ? '' : t(`units.${p.stock_unit}`)}`.trim()]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </span>
                {b.expires_at ? <ExpiryBadge date={b.expires_at} /> : <span className="text-xs text-ink-300">{t('inventory.noExpiry')}</span>}
              </label>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
