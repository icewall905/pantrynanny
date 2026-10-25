// One tap after an ADD: give what was just scanned an expiry and/or another location. Everything
// here is optional and skippable: the row hides itself on the next scan or after a while, and the
// buttons never take keyboard focus (a Bluetooth/USB scanner types into the page).
import clsx from 'clsx'
import { CalendarClock, MapPin } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { placeAdded } from '../api/stock'
import type { Category, Location, Product } from '../api/types'
import { chipDate, expiryChips, type ExpiryChip } from '../lib/expiry'
import { formatDate } from '../lib/format'
import { uuid } from '../offline'
import { NS } from './i18n'
import { resolvedLocation } from './place'

const PLACE_HIDE_MS = 30_000

export interface PlaceChipsProps {
  /** client_op_ids of the "add" ops behind the card (the scan plus any +N taps) */
  addOpIds: string[]
  /** every op in addOpIds has been applied by the server; otherwise the chips are disabled (a +N tap is syncing) */
  ready: boolean
  product: Product | null
  categories: Category[]
  locations: Location[]
  /** the location the scan asked for (null = automatic) */
  requestedLocationId: string | null
  toast: (text: string, tone?: 'amber' | 'info' | 'red') => void
}

const noFocus = (e: React.MouseEvent) => e.preventDefault()

export default function PlaceChips({ addOpIds, ready, product, categories, locations, requestedLocationId, toast }: PlaceChipsProps) {
  const { t, i18n } = useTranslation(NS)
  const category = product?.category_id ? categories.find((c) => c.id === product.category_id) : undefined
  const { chips, suggested } = expiryChips(category?.default_expiry_days)
  const [expiry, setExpiry] = useState<number | null>(null) // index of the chosen chip
  const [loc, setLoc] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [hidden, setHidden] = useState(false)
  const [touched, setTouched] = useState(0)
  const chosen = useRef<{ expires_at?: string | null; location_id?: string }>({})
  /** adds that already carry everything in `chosen` */
  const placed = useRef(new Set<string>())

  useEffect(() => {
    const id = setTimeout(() => setHidden(true), PLACE_HIDE_MS)
    return () => clearTimeout(id)
  }, [touched])

  // A +N tap after a choice: once it is applied, give it the same expiry/location (no extra tap).
  // Re-runs whenever a placement finishes (busy drops), so adds that arrived meanwhile are not missed.
  const opsKey = addOpIds.join(',')
  const latestIds = useRef(addOpIds)
  latestIds.current = addOpIds
  const failedFor = useRef<string | null>(null)
  useEffect(() => {
    if (!ready || busy || Object.keys(chosen.current).length === 0) return
    const todo = latestIds.current.filter((id) => !placed.current.has(id))
    if (todo.length === 0 || failedFor.current === opsKey) return
    setBusy(true)
    void (async () => {
      try {
        for (const id of todo) {
          await placeAdded({ client_op_id: uuid(), add_client_op_id: id, ...chosen.current })
          placed.current.add(id)
        }
      } catch (e) {
        failedFor.current = opsKey // no retry loop; the next tap or +N tries again
        console.warn('place failed', e)
        toast(t('place.failed'), 'amber')
      } finally {
        setBusy(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, opsKey, busy])

  if (hidden || addOpIds.length === 0) return null
  const here = loc ?? resolvedLocation(requestedLocationId, product, category, locations)

  const send = async (patch: { expires_at?: string | null; location_id?: string }, done: string) => {
    if (busy || !ready) return
    setBusy(true)
    setTouched((n) => n + 1)
    // Send everything chosen so far for this card, so a later tap never undoes an earlier one.
    const fields = { ...chosen.current, ...patch }
    try {
      const ok = new Set<string>()
      for (const id of addOpIds) {
        await placeAdded({ client_op_id: uuid(), add_client_op_id: id, ...fields })
        ok.add(id)
      }
      chosen.current = fields
      placed.current = ok
      toast(done)
      return true
    } catch (e) {
      console.warn('place failed', e)
      toast(t('place.failed'), 'amber')
      return false
    } finally {
      setBusy(false)
    }
  }

  const pickExpiry = async (i: number, c: ExpiryChip) => {
    const date = chipDate(c)
    const ok = await send({ expires_at: date }, date ? t('place.expirySet', { date: formatDate(date, i18n.language) }) : t('place.expiryCleared'))
    if (ok) setExpiry(i)
  }
  const pickLocation = async (l: Location) => {
    // `here` = where this card's stock was last placed (kept across +N taps), else where the scan put it
    if (l.id === here) return
    const ok = await send({ location_id: l.id }, t('place.moved', { name: l.name }))
    if (ok) setLoc(l.id)
  }

  const chipCls = (active: boolean, hint = false) =>
    clsx(
      'min-h-11 shrink-0 rounded-xl px-3 text-lg font-bold active:scale-95 disabled:opacity-50',
      active ? 'bg-white text-ink-900' : hint ? 'bg-white/25 ring-2 ring-honey-400' : 'bg-white/10 ring-1 ring-white/25',
    )

  return (
    <div className="flex flex-col gap-2" data-testid="place-chips" data-ready={ready} aria-busy={busy || !ready}>
      <div className="flex items-center gap-2 overflow-x-auto [scrollbar-width:none]" role="group" aria-label={t('place.expiry')}>
        <CalendarClock className="size-5 shrink-0 text-white/70" aria-hidden />
        {chips.map((c, i) => (
          <button
            key={`${c.key ?? 'cat'}-${c.days}`}
            type="button"
            disabled={busy || !ready}
            onMouseDown={noFocus}
            onClick={() => void pickExpiry(i, c)}
            aria-pressed={expiry === i}
            data-testid={`place-expiry-${c.key ?? 'cat'}`}
            data-suggested={i === suggested || undefined}
            className={chipCls(expiry === i, expiry === null && i === suggested)}
          >
            {c.key ? t(`place.chip.${c.key}`) : t('place.chip.days', { count: c.days ?? 0 })}
          </button>
        ))}
      </div>
      {locations.length > 1 && (
        <div className="flex items-center gap-2 overflow-x-auto [scrollbar-width:none]" role="group" aria-label={t('place.location')}>
          <MapPin className="size-5 shrink-0 text-white/70" aria-hidden />
          {locations.map((l) => (
            <button
              key={l.id}
              type="button"
              disabled={busy || !ready}
              onMouseDown={noFocus}
              onClick={() => void pickLocation(l)}
              aria-pressed={here === l.id}
              data-testid={`place-loc-${l.id}`}
              className={clsx(chipCls(here === l.id), 'text-base')}
            >
              {l.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
