import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { BarcodeLookupResult, Product } from '../api/types'
import { LookupTracker, reconcileProduct, type LookupDeps, type LookupUpdate } from './lookup'

const prod = (over: Partial<Product> = {}): Product =>
  ({ id: 'p1', version: 1, name: 'Letmælk', status: 'known', barcodes: [], ...over }) as unknown as Product
const placeholder = (over: Partial<Product> = {}) => prod({ name: '', status: 'unknown', ...over })
const found = (product: Product): BarcodeLookupResult => ({ status: 'found', product, source: null })
const created = (product: Product): BarcodeLookupResult => ({ status: 'created_placeholder', product, source: null })

/** Fake store + API: `localProduct` is what the IndexedDB lookup would return; data() fires subscribeData. */
function setup(remote: LookupDeps['remote']) {
  const listeners = new Set<() => void>()
  const state = { localProduct: null as Product | null }
  const cached: Product[] = []
  const deps: LookupDeps = {
    remote: vi.fn(remote),
    cache: async (p) => void cached.push(p),
    local: async () => state.localProduct,
    subscribe: (fn) => (listeners.add(fn), () => listeners.delete(fn)),
    retryDelaysMs: [500, 2000],
    slowMs: 10_000,
    recheckMs: [8000, 25_000],
  }
  const tracker = new LookupTracker(deps)
  const data = () => listeners.forEach((f) => f())
  return { tracker, deps, state, data, cached }
}

function watch(tracker: LookupTracker, id: number, code = '5701234567899') {
  const updates: LookupUpdate[] = []
  tracker.track(id, code, 'ean_13', (u) => updates.push(u))
  return updates
}

const flush = () => vi.advanceTimersByTimeAsync(0)

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('reconcileProduct', () => {
  it('a real product beats a placeholder, never the other way round', () => {
    expect(reconcileProduct(placeholder(), prod())?.status).toBe('known')
    expect(reconcileProduct(prod(), placeholder())?.status).toBe('known')
    expect(reconcileProduct(null, placeholder())?.status).toBe('unknown')
    expect(reconcileProduct(prod({ version: 3 }), prod({ version: 2 }))?.version).toBe(3)
    expect(reconcileProduct(prod({ version: 2 }), prod({ version: 3 }))?.version).toBe(3)
  })
})

describe('LookupTracker', () => {
  it('lookup resolves after the card was shown: looking first, then the product', async () => {
    let resolve!: (r: BarcodeLookupResult) => void
    const { tracker, cached } = setup(() => new Promise((r) => (resolve = r)))
    const updates = watch(tracker, 1)
    await flush()
    expect(updates).toEqual([]) // card keeps its initial neutral "looking" state
    resolve(found(prod()))
    await flush()
    expect(updates).toHaveLength(1)
    expect(updates[0]).toMatchObject({ phase: 'known', product: { name: 'Letmælk' } })
    expect(cached).toHaveLength(1)
  })

  it('result arrives only via the sync OpResult (store change); the lookup never answers', async () => {
    const { tracker, state, data } = setup(() => new Promise(() => {})) // hangs forever
    const updates = watch(tracker, 1)
    await vi.advanceTimersByTimeAsync(11_000)
    expect(updates.map((u) => u.phase)).toEqual(['slow']) // timeout fallback, still listening
    state.localProduct = prod({ name: 'Skyr' }) // sync applied OpResult.product
    data()
    await flush()
    expect(updates.at(-1)).toMatchObject({ phase: 'known', product: { name: 'Skyr' } })
  })

  it('a placeholder from the lookup is upgraded when the real product later shows up in the store', async () => {
    const { tracker, state, data } = setup(async () => created(placeholder()))
    const updates = watch(tracker, 1)
    await flush()
    expect(updates.at(-1)).toMatchObject({ phase: 'unknown' }) // genuinely unknown for now
    state.localProduct = prod() // pull / OpResult delivers the enriched product (same id!)
    data()
    await flush()
    expect(updates.at(-1)).toMatchObject({ phase: 'known', product: { name: 'Letmælk', status: 'known' } })
  })

  it('lookup fails (network, then 503) and succeeds on the retry', async () => {
    let calls = 0
    const { tracker, deps } = setup(async () => {
      calls++
      if (calls === 1) throw new TypeError('Failed to fetch')
      if (calls === 2) throw new ApiError(503, 'unavailable', null, null)
      return found(prod())
    })
    const updates = watch(tracker, 1)
    await vi.advanceTimersByTimeAsync(499)
    expect(deps.remote).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(deps.remote).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(2000)
    expect(deps.remote).toHaveBeenCalledTimes(3)
    expect(updates.at(-1)).toMatchObject({ phase: 'known' })
  })

  it('does not retry a 4xx answer', async () => {
    const { tracker, deps } = setup(async () => {
      throw new ApiError(400, 'bad', null, null)
    })
    watch(tracker, 1)
    await vi.advanceTimersByTimeAsync(5000)
    expect(deps.remote).toHaveBeenCalledTimes(1)
  })

  it('all retries fail: stays neutral, then slow, and still resolves from a later store update', async () => {
    const { tracker, state, data } = setup(async () => {
      throw new TypeError('offline')
    })
    const updates = watch(tracker, 1)
    await vi.advanceTimersByTimeAsync(12_000)
    expect(updates.map((u) => u.phase)).toEqual(['slow'])
    state.localProduct = prod()
    data()
    await flush()
    expect(updates.at(-1)).toMatchObject({ phase: 'known' })
  })

  it('second scan of the same code while the first lookup is pending: one request, both cards resolve', async () => {
    let resolve!: (r: BarcodeLookupResult) => void
    const { tracker, deps } = setup(() => new Promise((r) => (resolve = r)))
    const first = watch(tracker, 1)
    const second = watch(tracker, 2)
    tracker.forget(1) // the first card was replaced by the second one; its updates must not throw or leak
    await flush()
    expect(deps.remote).toHaveBeenCalledTimes(1)
    resolve(found(prod()))
    await flush()
    expect(first).toEqual([])
    expect(second.at(-1)).toMatchObject({ phase: 'known', product: { name: 'Letmælk' } })
  })

  it('two pending cards for the same code both resolve from one store update', async () => {
    const { tracker, state, data } = setup(() => new Promise(() => {}))
    const a = watch(tracker, 1)
    const b = watch(tracker, 2)
    state.localProduct = prod()
    data()
    await flush()
    expect(a.at(-1)?.phase).toBe('known')
    expect(b.at(-1)?.phase).toBe('known')
  })

  it('genuinely unknown: settles as unknown after the lookup completed, and no spinner states afterwards', async () => {
    const { tracker, deps } = setup(async (_c, _f, lookup) => (lookup ? created(placeholder()) : created(placeholder())))
    const updates = watch(tracker, 1)
    await flush()
    expect(updates).toHaveLength(1)
    expect(updates[0].phase).toBe('unknown')
    await vi.advanceTimersByTimeAsync(11_000) // slow timer must not demote a settled card
    expect(updates.map((u) => u.phase)).toEqual(['unknown'])
    // database-only re-checks at 8 s and 25 s found nothing new: label stays
    await vi.advanceTimersByTimeAsync(30_000)
    expect(deps.remote).toHaveBeenCalledWith('5701234567899', 'ean_13', false)
    expect(updates.map((u) => u.phase)).toEqual(['unknown'])
  })

  it('not_found without a product is also unknown', async () => {
    const { tracker } = setup(async () => ({ status: 'not_found', product: null, source: null }))
    const updates = watch(tracker, 1)
    await flush()
    expect(updates.at(-1)).toMatchObject({ phase: 'unknown', product: null })
  })

  it('an "unknown" answer is re-checked in the background and upgrades when enrichment finished', async () => {
    let enriched = false
    const { tracker } = setup(async (_c, _f, lookup) => (lookup || !enriched ? created(placeholder()) : found(prod())))
    const updates = watch(tracker, 1)
    await flush()
    enriched = true
    await vi.advanceTimersByTimeAsync(8100)
    expect(updates.at(-1)).toMatchObject({ phase: 'known', product: { name: 'Letmælk' } })
  })
})
