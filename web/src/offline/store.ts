// IndexedDB-backed offline store + sync engine. See docs/api-contract.md §3.
import { openDB, type IDBPDatabase } from 'idb'
import { ApiError, get, isNetworkError, post, qs } from '../api/client'
import type {
  ClientOp,
  Category,
  HouseholdSettings,
  Location,
  Me,
  Product,
  SyncChanges,
  SyncOpsResponse,
  SyncSnapshot,
  UUID,
} from '../api/types'
import { normalizeBarcode, type NormalizedBarcode } from './normalize'
import { uuid } from './uuid'
import type { FailedRecord, HistoryRecord, InventoryRecord, PendingRecord, SyncStatus } from './types'

export type NewOp = Omit<ClientOp, 'client_op_id' | 'occurred_at'> &
  Partial<Pick<ClientOp, 'client_op_id' | 'occurred_at'>>

const BATCH = 100
/** Consecutive HTTP 500s for a multi-op batch before it is split into single ops. */
const BATCH_500_SPLIT = 2
/** Consecutive HTTP 500s for one single op before it is parked in failedOps. */
const OP_500_LIMIT = 5
const HISTORY_MAX = 50
const BACKOFF_MIN = 1000
const BACKOFF_MAX = 30_000

type DB = IDBPDatabase<unknown>

export interface StoreOptions {
  dbName?: string
  /** Disable timers/listeners/auto sync (tests). */
  autoSync?: boolean
}

export interface BarcodeLookup {
  norm: NormalizedBarcode
  product: Product | null
}

export class OfflineStore {
  readonly dbName: string
  private dbp: Promise<DB> | null = null
  private status: SyncStatus
  private statusListeners = new Set<() => void>()
  private dataListeners = new Set<() => void>()
  private running: Promise<void> | null = null
  private again = false
  private forcePull = false
  /** Set after a 401: no polling/backoff until resume() (successful login or pairing). */
  private paused = false
  private retryDelay = BACKOFF_MIN
  private batch500 = 0
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private started = false
  private cleanup: (() => void)[] = []
  private channel: BroadcastChannel | null = null
  private autoSync: boolean

  constructor(opts: StoreOptions = {}) {
    this.dbName = opts.dbName ?? 'pantrynanny'
    this.autoSync = opts.autoSync ?? true
    this.status = {
      online: typeof navigator === 'undefined' ? true : navigator.onLine,
      pending: 0,
      syncing: false,
      lastSyncAt: null,
      error: null,
      failed: 0,
    }
    try {
      if (typeof BroadcastChannel !== 'undefined') {
        this.channel = new BroadcastChannel(`pn-offline-${this.dbName}`)
        this.channel.onmessage = () => {
          void this.refreshStatus()
          this.emitData()
        }
      }
    } catch {
      this.channel = null
    }
    void this.refreshStatus()
  }

  // ---------- db ----------
  private db(): Promise<DB> {
    if (this.dbp) return this.dbp
    const reset = (p: Promise<DB>) => {
      if (this.dbp === p) this.dbp = null
    }
    const p: Promise<DB> = openDB(this.dbName, 1, {
      upgrade(db) {
        db.createObjectStore('products', { keyPath: 'id' })
        db.createObjectStore('barcodeIndex')
        db.createObjectStore('inventory', { keyPath: 'product_id' })
        const pe = db.createObjectStore('pendingOps', { keyPath: 'client_op_id' })
        pe.createIndex('seq', 'seq', { unique: true })
        const f = db.createObjectStore('failedOps', { keyPath: 'client_op_id' })
        f.createIndex('seq', 'seq')
        db.createObjectStore('meta')
        const h = db.createObjectStore('scanHistory', { keyPath: 'client_op_id' })
        h.createIndex('seq', 'seq', { unique: true })
      },
      // iOS can kill the connection ("Connection to Indexed Database server lost") or another
      // tab/version can ask us to let go: drop the cached handle so the next call reopens.
      terminated: () => reset(p),
      blocking: () => {
        reset(p)
        void p.then((d) => d.close()).catch(() => undefined)
      },
    })
    p.catch(() => reset(p))
    this.dbp = p
    return p
  }

  /** Forget the cached connection (after InvalidStateError / UnknownError). */
  private async reopen() {
    const old = this.dbp
    this.dbp = null
    try {
      ;(await old)?.close()
    } catch {
      /* already dead */
    }
  }

  /** Close the DB (tests: simulate app restart). */
  async close() {
    this.dispose()
    if (this.dbp) (await this.dbp).close()
    this.dbp = null
  }

  dispose() {
    this.cleanup.forEach((f) => f())
    this.cleanup = []
    this.started = false
    if (this.retryTimer) clearTimeout(this.retryTimer)
    this.retryTimer = null
    this.channel?.close()
    this.channel = null
  }

  // ---------- status ----------
  subscribeStatus = (fn: () => void) => {
    this.statusListeners.add(fn)
    return () => this.statusListeners.delete(fn)
  }
  getStatus = () => this.status
  /** Fires whenever local data (queue, history, products, quantities) changes. */
  subscribeData = (fn: () => void) => {
    this.dataListeners.add(fn)
    return () => this.dataListeners.delete(fn)
  }
  private emitData() {
    this.dataListeners.forEach((f) => f())
  }
  private setStatus(patch: Partial<SyncStatus>) {
    const next = { ...this.status, ...patch }
    if (JSON.stringify(next) === JSON.stringify(this.status)) return
    this.status = next
    this.statusListeners.forEach((f) => f())
  }
  async refreshStatus() {
    try {
      const db = await this.db()
      const [pending, failed] = await Promise.all([db.count('pendingOps'), db.count('failedOps')])
      this.setStatus({ pending, failed })
    } catch {
      /* ignore */
    }
  }
  private announce() {
    this.emitData()
    try {
      this.channel?.postMessage('changed')
    } catch {
      /* ignore */
    }
  }

  // ---------- meta ----------
  async getMeta<T>(key: string): Promise<T | undefined> {
    return (await (await this.db()).get('meta', key)) as T | undefined
  }
  async setMeta(key: string, value: unknown) {
    await (await this.db()).put('meta', value, key)
  }
  async getDeviceId(): Promise<string> {
    const db = await this.db()
    let id = (await db.get('meta', 'device_id')) as string | undefined
    if (!id) {
      id = uuid()
      await db.put('meta', id, 'device_id')
    }
    return id
  }
  getLocations = async () => ((await this.getMeta<Location[]>('locations')) ?? []).filter((l) => !l.deleted_at)
  getCategories = async () => (await this.getMeta<Category[]>('categories')) ?? []
  getSettings = () => this.getMeta<HouseholdSettings>('settings')
  getMe = () => this.getMeta<Me>('me')
  setMe = (me: Me | null) => this.setMeta('me', me)

  // ---------- products ----------
  async cacheProduct(p: Product) {
    const db = await this.db()
    const tx = db.transaction(['products', 'barcodeIndex'], 'readwrite')
    await this.putProduct(tx, p)
    await tx.done
    this.emitData()
  }
  private async putProduct(
    tx: { objectStore(n: 'products' | 'barcodeIndex'): any }, // eslint-disable-line @typescript-eslint/no-explicit-any
    p: Product,
  ) {
    if (p.deleted_at) {
      await tx.objectStore('products').delete(p.id)
      for (const b of p.barcodes ?? []) await tx.objectStore('barcodeIndex').delete(b.code)
      return
    }
    await tx.objectStore('products').put(p)
    for (const b of p.barcodes ?? []) await tx.objectStore('barcodeIndex').put(p.id, b.code)
  }
  async getProduct(id: UUID): Promise<Product | undefined> {
    return (await this.db()).get('products', id)
  }
  async lookupBarcode(raw: string, symbology?: string | null): Promise<BarcodeLookup> {
    const db = await this.db()
    const norm = normalizeBarcode(raw, symbology)
    let id = (await db.get('barcodeIndex', norm.code)) as UUID | undefined
    id ??= (await db.get('barcodeIndex', `local:${raw}`)) as UUID | undefined
    const product = id ? ((await db.get('products', id)) as Product | undefined) ?? null : null
    return { norm, product }
  }

  // ---------- quantities ----------
  async pendingDelta(match: { productId?: UUID | null; codes?: string[] }): Promise<number> {
    const recs = (await (await this.db()).getAll('pendingOps')) as PendingRecord[]
    let sum = 0
    for (const r of recs) {
      if (
        (match.productId && r.product_key === match.productId) ||
        (r.code && match.codes?.includes(r.code))
      )
        sum += r.delta
    }
    return sum
  }
  /** server total + pending deltas (not clamped; UI clamps to ≥ 0). */
  async displayedQuantity(product: Product | null, norm?: NormalizedBarcode): Promise<number> {
    const db = await this.db()
    const codes = [...(product?.barcodes.map((b) => b.code) ?? []), ...(norm ? [norm.code] : [])]
    const inv = product ? ((await db.get('inventory', product.id)) as InventoryRecord | undefined) : undefined
    return (inv?.server_total ?? 0) + (await this.pendingDelta({ productId: product?.id, codes }))
  }

  // ---------- queue ----------
  /** Durable write; one transparent retry after reopening a dead IndexedDB connection. */
  async enqueueOp(op: NewOp): Promise<ClientOp> {
    const full = {
      ...op,
      client_op_id: op.client_op_id ?? uuid(),
      occurred_at: op.occurred_at ?? new Date().toISOString(),
    } as ClientOp
    try {
      await this.writeOp(full)
    } catch (e) {
      const name = (e as DOMException)?.name
      if (name !== 'InvalidStateError' && name !== 'UnknownError' && name !== 'TransactionInactiveError') throw e
      await this.reopen()
      await this.writeOp(full) // same client_op_id: the put is idempotent
    }
    this.announce()
    if (this.autoSync) void this.syncNow()
    return full
  }

  private async writeOp(full: ClientOp): Promise<void> {
    const norm = full.barcode ? normalizeBarcode(full.barcode, full.symbology) : null
    const db = await this.db()
    const tx = db.transaction(['pendingOps', 'meta', 'scanHistory', 'barcodeIndex'], 'readwrite')
    const meta = tx.objectStore('meta')
    const seq = (((await meta.get('seq')) as number | undefined) ?? 0) + 1
    await meta.put(seq, 'seq')
    const key =
      full.product_id ?? ((norm ? ((await tx.objectStore('barcodeIndex').get(norm.code)) as UUID | undefined) : undefined) ?? null)
    const hist = tx.objectStore('scanHistory')
    let delta = 0
    if (full.type === 'add') delta = full.quantity
    else if (full.type === 'remove') delta = -full.quantity
    else if (full.type === 'adjust') delta = full.quantity
    else if (full.type === 'undo' && full.undoes_client_op_id) {
      const h = (await hist.get(full.undoes_client_op_id)) as HistoryRecord | undefined
      if (h && !h.undone) {
        delta = -h.delta
        await hist.put({ ...h, undone: true })
      }
    }
    const rec: PendingRecord = {
      client_op_id: full.client_op_id,
      seq,
      op: full,
      delta,
      product_key: key,
      code: norm?.code ?? null,
      created: Date.now(),
    }
    await tx.objectStore('pendingOps').put(rec)
    if ((full.type === 'add' || full.type === 'remove') && full.barcode) {
      await hist.put({
        client_op_id: full.client_op_id,
        seq,
        at: full.occurred_at,
        type: full.type,
        barcode: full.barcode,
        code: norm!.code,
        symbology: full.symbology ?? null,
        product_id: key,
        delta,
        undone: false,
      } satisfies HistoryRecord)
      const over = ((await hist.count()) as number) - HISTORY_MAX
      if (over > 0) {
        let cur = await hist.index('seq').openCursor()
        for (let i = 0; cur && i < over; i++) {
          await cur.delete()
          cur = await cur.continue()
        }
      }
    }
    await tx.done
    this.setStatus({ pending: await db.count('pendingOps') })
  }

  /**
   * Undo a scan. Still pending and never uploaded → removed from the queue entirely;
   * otherwise an `undo` op is enqueued. Returns what happened.
   */
  async undoScan(clientOpId: string): Promise<'removed' | 'enqueued' | 'noop'> {
    const db = await this.db()
    const tx = db.transaction(['pendingOps', 'scanHistory'], 'readwrite')
    const hist = (await tx.objectStore('scanHistory').get(clientOpId)) as HistoryRecord | undefined
    if (!hist || hist.undone) {
      await tx.done
      return 'noop'
    }
    const pend = await tx.objectStore('pendingOps').get(clientOpId)
    // Only a never-sent op may vanish from the queue. Once an upload was attempted the server may
    // have applied it (timeout, dropped connection), so a compensating `undo` op is required.
    if (pend && !(pend as PendingRecord).sent) {
      await tx.objectStore('pendingOps').delete(clientOpId)
      await tx.objectStore('scanHistory').put({ ...hist, undone: true })
      await tx.done
      await this.refreshStatus()
      this.announce()
      return 'removed'
    }
    await tx.done
    await this.enqueueOp({
      type: 'undo',
      undoes_client_op_id: clientOpId,
      quantity: Math.abs(hist.delta) || 1,
      product_id: hist.product_id,
      barcode: hist.barcode,
      symbology: hist.symbology,
    })
    return 'enqueued'
  }

  async getHistory(limit = 20) {
    const db = await this.db()
    const out: (HistoryRecord & { product: Product | null; pending: boolean })[] = []
    const all = ((await db.getAllFromIndex('scanHistory', 'seq')) as HistoryRecord[]).reverse().slice(0, limit)
    const pendingIds = new Set(((await db.getAllKeys('pendingOps')) as string[]) ?? [])
    for (const h of all) {
      const pid = h.product_id ?? ((await db.get('barcodeIndex', h.code)) as UUID | undefined) ?? null
      const product = pid ? (((await db.get('products', pid)) as Product | undefined) ?? null) : null
      out.push({ ...h, product, pending: pendingIds.has(h.client_op_id) })
    }
    return out
  }

  async getPending(): Promise<PendingRecord[]> {
    return (await (await this.db()).getAllFromIndex('pendingOps', 'seq')) as PendingRecord[]
  }
  async getFailedOps(): Promise<FailedRecord[]> {
    return (await (await this.db()).getAllFromIndex('failedOps', 'seq')) as FailedRecord[]
  }
  async dismissFailedOp(id: string) {
    await (await this.db()).delete('failedOps', id)
    await this.refreshStatus()
    this.announce()
  }
  /** Put a rejected op back into the queue (e.g. after the user fixed the cause). */
  async retryFailedOp(id: string) {
    const db = await this.db()
    const tx = db.transaction(['failedOps', 'pendingOps', 'meta'], 'readwrite')
    const f = (await tx.objectStore('failedOps').get(id)) as FailedRecord | undefined
    if (!f) {
      await tx.done
      return
    }
    const meta = tx.objectStore('meta')
    const seq = (((await meta.get('seq')) as number | undefined) ?? 0) + 1
    await meta.put(seq, 'seq')
    await tx.objectStore('failedOps').delete(id)
    const delta = f.op.type === 'add' || f.op.type === 'adjust' ? f.op.quantity : f.op.type === 'remove' ? -f.op.quantity : 0
    await tx.objectStore('pendingOps').put({
      client_op_id: id,
      seq,
      op: f.op,
      delta,
      product_key: f.op.product_id ?? null,
      code: f.op.barcode ? normalizeBarcode(f.op.barcode, f.op.symbology).code : null,
      created: Date.now(),
    } satisfies PendingRecord)
    await tx.done
    await this.refreshStatus()
    this.announce()
    if (this.autoSync) void this.syncNow()
  }

  // ---------- account / household ----------
  /**
   * Call after every successful login/pairing. Switching to a different household wipes all local
   * data including unsent ops (they belong to the other household); returns how many were dropped.
   */
  async adoptSession(me: Me): Promise<{ droppedPending: number }> {
    const db = await this.db()
    const prev = (await db.get('meta', 'household_id')) as string | undefined
    let dropped = 0
    if (prev && prev !== me.household.id) {
      dropped = await db.count('pendingOps')
      await this.wipe(true)
    }
    await db.put('meta', me.household.id, 'household_id')
    await this.setMe(me)
    await this.setMeta('settings', me.settings)
    await this.refreshStatus()
    this.announce()
    return { droppedPending: dropped }
  }

  /** Logout: remove cached data and credentials-related state; unsent ops stay for the same household. */
  async clearForLogout() {
    await this.wipe(false)
    await this.refreshStatus()
    this.announce()
  }

  private async wipe(includePending: boolean) {
    const db = await this.db()
    const names = ['products', 'barcodeIndex', 'inventory', 'failedOps', 'scanHistory', ...(includePending ? ['pendingOps'] : [])] as const
    const tx = db.transaction([...names, 'meta'], 'readwrite')
    for (const n of names) await tx.objectStore(n).clear()
    const meta = tx.objectStore('meta')
    // keep: device_id, seq (monotonic), household_id (to detect a household switch)
    for (const k of ['cursor', 'lastSyncAt', 'locations', 'categories', 'settings', 'me']) await meta.delete(k)
    await tx.done
    if (includePending) this.setStatus({ pending: 0 })
  }

  // ---------- sync ----------
  syncNow(opts: { pull?: boolean } = {}): Promise<void> {
    if (opts.pull) this.forcePull = true
    if (this.paused) return Promise.resolve()
    if (this.running) {
      this.again = true
      return this.running
    }
    this.running = (async () => {
      try {
        do {
          this.again = false
          await this.locked(() => this.cycle())
        } while (this.again)
      } finally {
        this.running = null
      }
    })()
    return this.running
  }

  private locked(fn: () => Promise<void>): Promise<void> {
    const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined
    if (!locks) return fn()
    return locks.request(`pn-sync-${this.dbName}`, { ifAvailable: true }, async (lock) => {
      if (lock) await fn()
    }) as Promise<void>
  }

  private async cycle() {
    this.setStatus({ syncing: true })
    try {
      await this.push()
      if (this.forcePull || !(await this.getMeta('cursor'))) {
        this.forcePull = false
        await this.pull()
      }
      this.retryDelay = BACKOFF_MIN
      const now = new Date().toISOString()
      await this.setMeta('lastSyncAt', now)
      this.setStatus({ syncing: false, online: navigator.onLine, lastSyncAt: now, error: null })
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        // Not (or no longer) signed in: stop polling until login/pairing succeeds.
        this.paused = true
        this.again = false
        this.setStatus({ syncing: false, online: navigator.onLine, error: 'unauthorized' })
        return
      }
      const net = isNetworkError(e)
      this.setStatus({
        syncing: false,
        online: net ? false : navigator.onLine,
        error: net ? 'offline' : e instanceof Error ? e.message : String(e),
      })
      this.again = false
      this.scheduleRetry()
    } finally {
      await this.refreshStatus()
      this.announce()
    }
  }

  /** Call after a successful login / kiosk pairing. */
  resume() {
    this.paused = false
    this.retryDelay = BACKOFF_MIN
    return this.syncNow({ pull: true })
  }

  private scheduleRetry() {
    if (!this.autoSync) return
    if (this.retryTimer) clearTimeout(this.retryTimer)
    const d = this.retryDelay
    this.retryDelay = Math.min(this.retryDelay * 2, BACKOFF_MAX)
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null
      void this.syncNow()
    }, d)
  }

  private async push() {
    const db = await this.db()
    const device_id = await this.getDeviceId()
    let size = BATCH
    for (;;) {
      const batch = ((await db.getAllFromIndex('pendingOps', 'seq', undefined, size)) as PendingRecord[]) ?? []
      if (!batch.length) return
      // Durably mark as "sent" BEFORE the POST: from now on the server may have applied them.
      {
        const tx = db.transaction('pendingOps', 'readwrite')
        for (const r of batch) if (!r.sent) await tx.store.put({ ...r, sent: true })
        await tx.done
      }
      try {
        let res: SyncOpsResponse
        try {
          res = await post<SyncOpsResponse>('/sync/ops', { device_id, ops: batch.map((b) => b.op) }, { timeoutMs: 20_000, silent401: true })
        } catch (e) {
          if (e instanceof ApiError && [400, 413, 422].includes(e.status)) {
            if (batch.length > 1) {
              size = 1
              continue
            }
            await this.fail(batch[0], `${e.status}: ${e.message}`, 'bad_request')
            continue
          }
          if (e instanceof ApiError && e.status === 500) {
            // A poison op must never block the queue forever. 502/503/504/network stay retry-forever.
            if (batch.length > 1) {
              if (++this.batch500 >= BATCH_500_SPLIT) {
                size = 1
                continue
              }
              throw e
            }
            const rec = batch[0]
            const n = (rec.fails500 ?? 0) + 1
            if (n >= OP_500_LIMIT) {
              await this.fail(rec, `${e.status}: ${e.message}`, 'server_error')
              this.batch500 = 0
              continue
            }
            await db.put('pendingOps', { ...rec, fails500: n })
            throw e
          }
          throw e
        }
        this.batch500 = 0
        const byId = new Map(res.results.map((r) => [r.client_op_id, r]))
        if (batch.some((b) => !byId.has(b.client_op_id))) throw new Error('incomplete sync response')
        for (const rec of batch) {
          const r = byId.get(rec.client_op_id)!
          if (r.status === 'rejected') {
            await this.fail(rec, r.error ?? r.error_code ?? 'rejected', r.error_code ?? null)
            continue
          }
          const tx = db.transaction(['pendingOps', 'products', 'barcodeIndex', 'inventory'], 'readwrite')
          await tx.objectStore('pendingOps').delete(rec.client_op_id)
          if (r.product) {
            await this.putProduct(tx, r.product)
            if (r.status === 'applied' && r.total_quantity != null) {
              const old = (await tx.objectStore('inventory').get(r.product.id)) as InventoryRecord | undefined
              await tx.objectStore('inventory').put({
                product_id: r.product.id,
                server_total: r.total_quantity,
                batches: old?.batches ?? [],
              } satisfies InventoryRecord)
            }
          }
          await tx.done
        }
      } finally {
        await this.refreshStatus()
        this.emitData()
      }
    }
  }

  private async fail(rec: PendingRecord, error: string, error_code: string | null = null) {
    const db = await this.db()
    const tx = db.transaction(['pendingOps', 'failedOps'], 'readwrite')
    await tx.objectStore('failedOps').put({
      client_op_id: rec.client_op_id,
      seq: rec.seq,
      op: rec.op,
      error,
      error_code,
      at: new Date().toISOString(),
    } satisfies FailedRecord)
    await tx.objectStore('pendingOps').delete(rec.client_op_id)
    await tx.done
  }

  private async pull() {
    const cursor = await this.getMeta<string>('cursor')
    if (cursor) {
      const ch = await get<SyncChanges>(`/sync/changes${qs({ since: cursor })}`, { timeoutMs: 30_000, silent401: true })
      if (!ch.full_resync_required) {
        await this.applyPull(ch, false)
        return
      }
    }
    const snap = await get<SyncSnapshot>('/sync/snapshot', { timeoutMs: 60_000, silent401: true })
    await this.applyPull(snap, true)
  }

  private async applyPull(d: SyncSnapshot | SyncChanges, replace: boolean) {
    const db = await this.db()
    const tx = db.transaction(['products', 'barcodeIndex', 'inventory', 'meta'], 'readwrite')
    if (replace) {
      await tx.objectStore('products').clear()
      await tx.objectStore('barcodeIndex').clear()
      await tx.objectStore('inventory').clear()
    }
    for (const p of d.products) await this.putProduct(tx, p)
    for (const inv of d.inventory)
      await tx.objectStore('inventory').put({
        product_id: inv.product_id,
        server_total: inv.total_quantity,
        batches: inv.batches,
      } satisfies InventoryRecord)
    const meta = tx.objectStore('meta')
    const merge = async <T extends { id: string }>(key: string, items: T[]) => {
      if (replace) return void (await meta.put(items, key))
      if (!items.length) return
      const old = ((await meta.get(key)) as T[] | undefined) ?? []
      const m = new Map(old.map((o) => [o.id, o]))
      items.forEach((i) => m.set(i.id, i))
      await meta.put([...m.values()], key)
    }
    await merge('locations', d.locations)
    await merge('categories', d.categories)
    if ('settings' in d && d.settings) await meta.put(d.settings, 'settings')
    await meta.put(d.cursor, 'cursor')
    await tx.done
    this.emitData()
  }

  // ---------- lifecycle (foreground-driven) ----------
  start() {
    if (this.started || typeof window === 'undefined') return
    this.started = true
    this.autoSync = true
    const vis = () => document.visibilityState === 'visible'
    const on = (t: EventTarget, ev: string, fn: () => void) => {
      t.addEventListener(ev, fn)
      this.cleanup.push(() => t.removeEventListener(ev, fn))
    }
    on(window, 'online', () => {
      this.retryDelay = BACKOFF_MIN
      void this.syncNow({ pull: true })
    })
    on(window, 'offline', () => this.setStatus({ online: false }))
    on(document, 'visibilitychange', () => {
      if (vis()) void this.syncNow({ pull: true })
    })
    const push = setInterval(() => vis() && void this.syncNow(), 30_000)
    const pull = setInterval(() => vis() && void this.syncNow({ pull: true }), 60_000)
    this.cleanup.push(() => clearInterval(push), () => clearInterval(pull))
    try {
      void navigator.storage?.persist?.()
    } catch {
      /* ignore */
    }
    // Background Sync as progressive enhancement (not on iOS).
    void navigator.serviceWorker?.ready
      ?.then((reg) => (reg as ServiceWorkerRegistration & { sync?: { register(t: string): Promise<void> } }).sync?.register('pn-sync'))
      .catch(() => undefined)
    void this.syncNow({ pull: true })
  }
}
