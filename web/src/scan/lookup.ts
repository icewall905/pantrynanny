// Resolving the "what is this barcode" question for the last-scanned card after a local cache miss.
//
// The scan itself is counted immediately (op enqueued before any network). The card, however, must not say
// "unknown" until the answer is really unknown. Answers can arrive from several places, so the tracker listens to
// all of them: the by-barcode lookup response (retried on network/5xx errors), and the local store, which is
// filled by the sync OpResult.product and by snapshot/changes pulls (store.subscribeData).
import { ApiError } from '../api/client'
import type { BarcodeLookupResult, Product } from '../api/types'

/** looking = neutral spinner; slow = nothing known after SLOW_MS (keeps listening); known / unknown = settled */
export type CardPhase = 'looking' | 'slow' | 'known' | 'unknown'

export interface LookupUpdate {
  phase: CardPhase
  product: Product | null
}

export const isKnownProduct = (p: Product | null | undefined): p is Product => !!p && p.status !== 'unknown'

/** Which product to show: a real product beats a placeholder; for the same id the newer version wins. */
export function reconcileProduct(cur: Product | null, incoming: Product | null): Product | null {
  if (!incoming) return cur
  if (!cur) return incoming
  const curKnown = isKnownProduct(cur)
  const inKnown = isKnownProduct(incoming)
  if (inKnown !== curKnown) return inKnown ? incoming : cur
  if (cur.id === incoming.id && incoming.version < cur.version) return cur
  return incoming
}

export interface LookupDeps {
  /** GET /products/by-barcode/...; `lookup=false` = database only (no external providers) */
  remote(barcode: string, format: string, lookup: boolean): Promise<BarcodeLookupResult>
  cache(p: Product): Promise<void>
  local(barcode: string, format: string): Promise<Product | null>
  /** local data changed (sync result applied, pull, product cached) */
  subscribe(fn: () => void): () => void
  /** backoff between retries of a failing lookup */
  retryDelaysMs?: number[]
  /** show the "looked up in the background" fallback after this long without an answer */
  slowMs?: number
  /** when the answer was "unknown", ask the database again after these delays (enrichment may finish later) */
  recheckMs?: number[]
  /** stop tracking a card after this long (default 2 min) */
  ttlMs?: number
}

export const DEFAULT_RETRY_DELAYS = [500, 2000]
export const SLOW_MS = 10_000
export const DEFAULT_RECHECK = [8000, 25_000]
export const TTL_MS = 120_000

/** 4xx are answers (bad request, auth): retrying will not help. Everything else (network, timeout, 5xx) is retried. */
export function retryable(e: unknown): boolean {
  return !(e instanceof ApiError && e.status >= 400 && e.status < 500)
}

interface Entry {
  id: number
  barcode: string
  format: string
  onUpdate(u: LookupUpdate): void
  phase: CardPhase
  product: Product | null
  timers: ReturnType<typeof setTimeout>[]
}

export class LookupTracker {
  private entries = new Map<number, Entry>()
  private inflight = new Map<string, Promise<BarcodeLookupResult>>()
  private off: () => void
  private disposed = false

  private deps: LookupDeps
  constructor(deps: LookupDeps) {
    this.deps = deps
    this.off = deps.subscribe(() => void this.onData())
  }

  /**
   * Start resolving `barcode` for card `id`. The card starts in phase 'looking', or 'unknown' when the local cache
   * already holds a placeholder (`initial`): then the lookup only tries to upgrade it.
   */
  track(id: number, barcode: string, format: string, onUpdate: (u: LookupUpdate) => void, initial: Product | null = null) {
    const e: Entry = { id, barcode, format, onUpdate, phase: initial ? 'unknown' : 'looking', product: initial, timers: [] }
    this.entries.set(id, e)
    e.timers.push(setTimeout(() => this.forget(id), this.deps.ttlMs ?? TTL_MS))
    e.timers.push(
      setTimeout(() => {
        if (e.phase === 'looking') this.set(e, 'slow', e.product)
      }, this.deps.slowMs ?? SLOW_MS),
    )
    void this.run(e)
  }

  forget(id: number) {
    const e = this.entries.get(id)
    if (e) this.clear(e)
    this.entries.delete(id)
  }

  dispose() {
    this.disposed = true
    this.off()
    for (const e of this.entries.values()) this.clear(e)
    this.entries.clear()
  }

  private clear(e: Entry) {
    e.timers.forEach(clearTimeout)
    e.timers = []
  }

  private set(e: Entry, phase: CardPhase, product: Product | null) {
    if (this.disposed || this.entries.get(e.id) !== e) return
    const next = reconcileProduct(e.product, product)
    const changed = phase !== e.phase || next?.id !== e.product?.id || next?.version !== e.product?.version || next?.status !== e.product?.status
    e.phase = phase
    e.product = next
    if (phase === 'known') {
      this.clear(e) // settled for good; a later rename is picked up by the card's own refresh
      this.entries.delete(e.id)
    }
    if (changed) e.onUpdate({ phase, product: next })
  }

  /** A product for this card arrived from some source. */
  private apply(e: Entry, p: Product | null) {
    if (!p) return
    const merged = reconcileProduct(e.product, p)
    this.set(e, isKnownProduct(merged) ? 'known' : 'unknown', merged)
  }

  private fetch(e: Entry, lookup: boolean): Promise<BarcodeLookupResult> {
    const key = `${e.barcode}|${e.format}|${lookup}`
    let p = this.inflight.get(key)
    if (!p) {
      p = this.fetchRetrying(e, lookup).finally(() => this.inflight.delete(key))
      this.inflight.set(key, p)
    }
    return p
  }

  private async fetchRetrying(e: Entry, lookup: boolean): Promise<BarcodeLookupResult> {
    const delays = lookup ? (this.deps.retryDelaysMs ?? DEFAULT_RETRY_DELAYS) : []
    for (let i = 0; ; i++) {
      try {
        return await this.deps.remote(e.barcode, e.format, lookup)
      } catch (err) {
        if (i >= delays.length || !retryable(err) || this.disposed) throw err
        await new Promise((r) => setTimeout(r, delays[i]))
      }
    }
  }

  private async run(e: Entry) {
    try {
      const r = await this.fetch(e, true)
      if (r.product) await this.deps.cache(r.product).catch(() => undefined)
      if (this.entries.get(e.id) !== e) return
      if (r.product) this.apply(e, r.product)
      else this.set(e, 'unknown', e.product) // not_found: genuinely unknown
    } catch {
      return // offline / server down after all retries: stay neutral and keep listening to the store
    }
    if (this.entries.get(e.id) === e && e.phase === 'unknown') this.scheduleRecheck(e)
  }

  private scheduleRecheck(e: Entry) {
    for (const delay of this.deps.recheckMs ?? DEFAULT_RECHECK) {
      e.timers.push(
        setTimeout(() => {
          void (async () => {
            try {
              const r = await this.fetch(e, false)
              if (r.product && this.entries.get(e.id) === e) {
                await this.deps.cache(r.product).catch(() => undefined)
                this.apply(e, r.product)
              }
            } catch {
              /* try again at the next delay */
            }
          })()
        }, delay),
      )
    }
  }

  /** Local data changed: re-resolve every unsettled card by code (covers sync OpResult.product and pulls). */
  private async onData() {
    for (const e of [...this.entries.values()]) {
      try {
        const p = await this.deps.local(e.barcode, e.format)
        if (p && this.entries.get(e.id) === e) this.apply(e, p)
      } catch {
        /* ignore */
      }
    }
  }
}
