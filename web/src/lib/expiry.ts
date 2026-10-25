// One-tap expiry chips (scanner + bulk fix-up). Pure helpers so they can be tested.
import type { ISODate } from '../api/types'
import { todayISO } from './format'

export interface ExpiryChip {
  /** i18n key suffix under `scan.place.chip.*`, or null for a category's own default (`+N d`) */
  key: string | null
  /** days from today (null with no `months` = no expiry) */
  days: number | null
  /** calendar months from today, clamped to the month's end (like java.time plusMonths) */
  months?: number
}

export const EXPIRY_PRESETS: ExpiryChip[] = [
  { key: 'd3', days: 3 },
  { key: 'w1', days: 7 },
  { key: 'm1', days: null, months: 1 },
  { key: 'm6', days: null, months: 6 },
  { key: 'none', days: null },
]

/** Local date `days` from `now` as YYYY-MM-DD (calendar days, DST-safe). */
export function addDaysISO(days: number, now = new Date()): ISODate {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days, 12)
  return todayISO(d)
}

/** Local date `months` calendar months from `now`; 31 Jan + 1 → 28/29 Feb. */
export function addMonthsISO(months: number, now = new Date()): ISODate {
  const y = now.getFullYear()
  const m = now.getMonth() + months
  const last = new Date(y, m + 1, 0, 12).getDate() // last day of the target month
  return todayISO(new Date(y, m, Math.min(now.getDate(), last), 12))
}

/**
 * The chips to show for a category whose default shelf life is `defaultDays` (null = none). A
 * default equal to a day preset (+3 d, +1 w) highlights it; anything else (month chips are never
 * matched: a month is not a fixed number of days) adds its own `+N d` chip before "none".
 * Returns the chips and the index of the highlighted one (-1 = none).
 */
export function expiryChips(defaultDays: number | null | undefined): { chips: ExpiryChip[]; suggested: number } {
  if (defaultDays === null || defaultDays === undefined || defaultDays < 0) return { chips: EXPIRY_PRESETS, suggested: -1 }
  const i = EXPIRY_PRESETS.findIndex((c) => !c.months && c.days === defaultDays)
  if (i >= 0) return { chips: EXPIRY_PRESETS, suggested: i }
  const chips = [...EXPIRY_PRESETS]
  chips.splice(chips.length - 1, 0, { key: null, days: defaultDays })
  return { chips, suggested: chips.length - 2 }
}

/** The `expires_at` value a chip sends: a date, or null to clear. */
export const chipDate = (c: ExpiryChip, now = new Date()): ISODate | null =>
  c.months ? addMonthsISO(c.months, now) : c.days === null ? null : addDaysISO(c.days, now)
