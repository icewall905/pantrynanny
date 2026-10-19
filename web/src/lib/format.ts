import clsx, { type ClassValue } from 'clsx'
import type { ISODate, ShoppingItem, Category } from '../api/types'

export const cn = (...v: ClassValue[]) => clsx(v)

export function todayISO(now = new Date()): ISODate {
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** Whole days from today until the given date (negative = in the past). */
export function daysUntil(date: ISODate, now = new Date()): number {
  const [y, m, d] = date.split('-').map(Number)
  const target = Date.UTC(y, m - 1, d)
  const t = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.round((target - t) / 86_400_000)
}

export type ExpiryState = 'none' | 'ok' | 'soon' | 'expired'

export function expiryState(date: ISODate | null | undefined, soonDays: number, now = new Date()): ExpiryState {
  if (!date) return 'none'
  const n = daysUntil(date, now)
  if (n < 0) return 'expired'
  if (n <= soonDays) return 'soon'
  return 'ok'
}

export function formatQty(n: number, locale = 'da'): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(n)
}

export function formatDate(date: string | null | undefined, locale = 'da'): string {
  if (!date) return ''
  const d = date.length <= 10 ? new Date(`${date}T12:00:00`) : new Date(date)
  return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric' }).format(d)
}

export function formatDateTime(date: string, locale = 'da'): string {
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(date))
}

/** Stable pastel colour index from a string, for placeholder tiles. */
export function hashIndex(s: string, mod: number): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h % mod
}

export interface ShoppingGroup {
  key: string
  category: Category | null
  items: ShoppingItem[]
}

/** Group shopping items by category (category order first, "no category" last); unchecked before checked. */
export function groupShopping(items: ShoppingItem[], categories: Category[]): ShoppingGroup[] {
  const byCat = new Map<string, ShoppingItem[]>()
  for (const it of items) {
    const k = it.category_id ?? ''
    byCat.set(k, [...(byCat.get(k) ?? []), it])
  }
  const sorted = [...categories].sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name))
  const groups: ShoppingGroup[] = []
  for (const c of sorted) {
    const its = byCat.get(c.id)
    if (its) groups.push({ key: c.id, category: c, items: sortChecked(its) })
  }
  const rest = byCat.get('')
  const known = new Set(sorted.map((c) => c.id))
  const orphan = [...byCat.entries()].filter(([k]) => k && !known.has(k)).flatMap(([, v]) => v)
  const noCat = [...(rest ?? []), ...orphan]
  if (noCat.length) groups.push({ key: '', category: null, items: sortChecked(noCat) })
  return groups
}

function sortChecked(items: ShoppingItem[]): ShoppingItem[] {
  return [...items].sort((a, b) => Number(a.checked) - Number(b.checked) || a.name.localeCompare(b.name, 'da'))
}

/** Plain-text shopping list (open items only), grouped by category. */
export function shoppingToText(
  items: ShoppingItem[],
  categories: Category[],
  noCategoryLabel: string,
  unitLabel: (u: string) => string = (u) => u,
): string {
  const open = items.filter((i) => !i.checked)
  const lines: string[] = []
  for (const g of groupShopping(open, categories)) {
    lines.push(`${g.category?.name ?? noCategoryLabel}:`)
    for (const it of g.items) {
      const qty = it.quantity !== 1 || it.unit ? `${formatQty(it.quantity)}${it.unit ? ' ' + unitLabel(it.unit) : ' x'} ` : ''
      lines.push(`- ${qty}${it.name}`.replace(/ x $/, ''))
    }
    lines.push('')
  }
  return lines.join('\n').trim()
}
