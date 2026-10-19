import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ClientOp, OpResult, Product } from '../api/types'
import { OfflineStore } from './store'

let n = 0
const stores: OfflineStore[] = []
function mk(name?: string) {
  const s = new OfflineStore({ dbName: name ?? `t${++n}-${Math.random()}`, autoSync: false })
  stores.push(s)
  return s
}

function product(id: string, code: string, name = 'Mælk'): Product {
  return {
    id, version: 1, name, brand: null, category_id: null, default_location_id: null, image_url: null,
    package_size: null, package_unit: null, stock_unit: 'pcs', min_stock: null, ingredients: null,
    allergens: [], nutrition: null, description: null, countries: [],
    barcodes: [{ code, raw: code, symbology: 'ean_13' }], aliases: [], status: 'known', source: 'user',
    source_attribution: null, lookup_confidence: null, locked_fields: [], created_at: '', updated_at: '', deleted_at: null,
  }
}

/** Minimal in-memory server implementing the idempotent /sync/ops contract. */
function fakeServer() {
  const seen = new Map<string, OpResult>()
  const requests: ClientOp[][] = []
  const totals = new Map<string, number>()
  const state = { down: false, dropAfterApply: false, unauth: false, rejectIds: new Set<string>() }
  const P = product('p1', '05701234567899')
  const handler = async (url: string, init?: RequestInit) => {
    if (state.down) throw new TypeError('Failed to fetch')
    if (state.unauth) return new Response('{"detail":"no"}', { status: 401, headers: { 'content-type': 'application/json' } })
    const json = (b: unknown, status = 200) =>
      new Response(JSON.stringify(b), { status, headers: { 'content-type': 'application/json' } })
    if (url.endsWith('/api/sync/ops')) {
      const body = JSON.parse(String(init!.body)) as { ops: ClientOp[] }
      requests.push(body.ops)
      const results: OpResult[] = body.ops.map((op) => {
        const prev = seen.get(op.client_op_id)
        if (prev) return { ...prev, status: 'duplicate' }
        if (state.rejectIds.has(op.client_op_id))
          return { client_op_id: op.client_op_id, status: 'rejected', error: 'nope', transaction_id: null, product: null, total_quantity: null }
        const d = op.type === 'remove' ? -op.quantity : op.type === 'undo' ? -1 : op.quantity
        totals.set('p1', (totals.get('p1') ?? 0) + d)
        const r: OpResult = { client_op_id: op.client_op_id, status: 'applied', error: null, transaction_id: 't', product: P, total_quantity: totals.get('p1')! }
        seen.set(op.client_op_id, r)
        return r
      })
      if (state.dropAfterApply) {
        state.dropAfterApply = false
        throw new TypeError('timeout') // applied on the server, response lost
      }
      return json({ results, server_time: '' })
    }
    if (url.includes('/api/sync/snapshot'))
      return json({ cursor: 'c1', products: [P], inventory: [{ product_id: 'p1', total_quantity: totals.get('p1') ?? 0, batches: [] }], locations: [], categories: [], settings: { scan_rearm_ms: 600 } })
    if (url.includes('/api/sync/changes'))
      return json({ cursor: 'c2', products: [], inventory: [], locations: [], categories: [], full_resync_required: false })
    return json({}, 404)
  }
  return { state, requests, totals, seen, handler }
}

let srv: ReturnType<typeof fakeServer>
beforeEach(() => {
  srv = fakeServer()
  vi.stubGlobal('fetch', vi.fn((u: string, i?: RequestInit) => srv.handler(String(u), i)))
})
afterEach(async () => {
  for (const s of stores.splice(0)) await s.close()
  vi.unstubAllGlobals()
})

const add = (s: OfflineStore, over: Partial<ClientOp> = {}) =>
  s.enqueueOp({ type: 'add', barcode: '5701234567899', symbology: 'ean_13', quantity: 1, ...over })

describe('offline queue', () => {
  it('persists ops and survives a restart', async () => {
    srv.state.down = true
    const a = mk('restart-db')
    const op = await add(a)
    await a.close()
    const b = mk('restart-db')
    const pend = await b.getPending()
    expect(pend.map((p) => p.client_op_id)).toEqual([op.client_op_id])
    await b.refreshStatus()
    expect(b.getStatus().pending).toBe(1)
  })

  it('keeps ops while backend is down and uploads exactly once after reconnect', async () => {
    const s = mk()
    srv.state.down = true
    await add(s)
    await add(s)
    await s.syncNow()
    expect(s.getStatus().error).toBe('offline')
    expect(s.getStatus().online).toBe(false)
    expect((await s.getPending()).length).toBe(2)
    srv.state.down = false
    await s.syncNow()
    expect((await s.getPending()).length).toBe(0)
    expect(srv.seen.size).toBe(2)
    expect(srv.totals.get('p1')).toBe(2)
    await s.syncNow()
    expect(srv.requests.length).toBe(1) // nothing re-sent
  })

  it('handles a lost response: replay returns duplicate, applied once', async () => {
    const s = mk()
    const op = await add(s)
    // server applied it but the client never saw the response
    await srv.handler('/api/sync/ops', { method: 'POST', body: JSON.stringify({ ops: [op] }) })
    await s.syncNow()
    expect((await s.getPending()).length).toBe(0)
    expect(srv.totals.get('p1')).toBe(1)
    expect(s.getStatus().error).toBeNull()
  })

  it('moves rejected ops to failedOps, never drops them', async () => {
    const s = mk()
    const bad = await add(s)
    const good = await add(s)
    srv.state.rejectIds.add(bad.client_op_id)
    await s.syncNow()
    const failed = await s.getFailedOps()
    expect(failed.map((f) => f.client_op_id)).toEqual([bad.client_op_id])
    expect(failed[0].error).toBe('nope')
    expect((await s.getPending()).length).toBe(0)
    expect(srv.seen.has(good.client_op_id)).toBe(true)
    expect(s.getStatus().failed).toBe(1)
    await s.dismissFailedOp(bad.client_op_id)
    expect((await s.getFailedOps()).length).toBe(0)
  })

  it('uploads in order and in batches of at most 100', async () => {
    const s = mk()
    const ids: string[] = []
    for (let i = 0; i < 230; i++) ids.push((await add(s)).client_op_id)
    await s.syncNow()
    expect(srv.requests.map((r) => r.length)).toEqual([100, 100, 30])
    expect(srv.requests.flat().map((o) => o.client_op_id)).toEqual(ids)
  })

  it('computes displayed quantity = server total + pending deltas', async () => {
    const s = mk()
    const p = product('p1', '05701234567899')
    await s.cacheProduct(p)
    srv.state.down = true
    await add(s, { product_id: 'p1' })
    await add(s, { product_id: 'p1' })
    await s.enqueueOp({ type: 'remove', barcode: '5701234567899', quantity: 1 }) // resolved via barcodeIndex
    expect(await s.displayedQuantity(p)).toBe(1)
    srv.state.down = false
    srv.totals.set('p1', 5)
    await s.syncNow({ pull: true })
    // after sync: server has 5+1+1-1 = 6, nothing pending
    expect(await s.displayedQuantity(p)).toBe(6)
    srv.state.down = true
    await add(s)
    expect(await s.displayedQuantity(p)).toBe(7)
  })

  it('tracks pending quantity for barcodes unknown locally', async () => {
    const s = mk()
    await add(s, { barcode: '4000000000000' }) // not a valid ean → local:
    await add(s, { barcode: '4000000000000' })
    const { norm, product: p } = await s.lookupBarcode('4000000000000')
    expect(p).toBeNull()
    expect(await s.displayedQuantity(null, norm)).toBe(2)
  })

  it('undo of a pending op removes it from the queue and reverts quantity', async () => {
    const s = mk()
    const p = product('p1', '05701234567899')
    await s.cacheProduct(p)
    const op = await add(s)
    expect(await s.displayedQuantity(p)).toBe(1)
    expect(await s.undoScan(op.client_op_id)).toBe('removed')
    expect(await s.displayedQuantity(p)).toBe(0)
    expect((await s.getPending()).length).toBe(0)
    expect((await s.getHistory())[0].undone).toBe(true)
    expect(await s.undoScan(op.client_op_id)).toBe('noop')
  })

  it('undo of a synced op enqueues an undo op referencing the original', async () => {
    const s = mk()
    const p = product('p1', '05701234567899')
    const op = await add(s)
    await s.syncNow()
    expect(await s.undoScan(op.client_op_id)).toBe('enqueued')
    const [u] = await s.getPending()
    expect(u.op.type).toBe('undo')
    expect(u.op.undoes_client_op_id).toBe(op.client_op_id)
    expect(await s.displayedQuantity(p)).toBe(0) // server 1 + pending -1
  })

  it('pull: snapshot first, then changes; caches products by barcode', async () => {
    const s = mk()
    await s.syncNow({ pull: true })
    const r = await s.lookupBarcode('5701234567899', 'ean_13')
    expect(r.product?.id).toBe('p1')
    expect(await s.getMeta('cursor')).toBe('c1')
    await s.syncNow({ pull: true })
    expect(await s.getMeta('cursor')).toBe('c2')
  })

  it('keeps history to the last 50 scans', async () => {
    const s = mk()
    for (let i = 0; i < 55; i++) await add(s)
    expect((await s.getHistory(100)).length).toBe(50)
  })

  it('undo after an upload whose response was lost (server applied it) compensates instead of deleting', async () => {
    const s = mk()
    const p = product('p1', '05701234567899')
    await s.cacheProduct(p)
    const op = await add(s)
    srv.state.dropAfterApply = true
    await s.syncNow() // server applied, client saw a timeout
    expect(srv.totals.get('p1')).toBe(1)
    expect((await s.getPending()).length).toBe(1) // still queued: outcome unknown
    expect(await s.undoScan(op.client_op_id)).toBe('enqueued') // NOT 'removed'
    await s.syncNow()
    expect(srv.totals.get('p1')).toBe(0)
    expect((await s.getPending()).length).toBe(0)
    expect(srv.requests.at(-1)!.map((o) => o.type)).toEqual(['add', 'undo']) // replay + compensation, in order
  })

  it('marks ops as sent durably before the POST', async () => {
    const s = mk('sent-db')
    await add(s)
    srv.state.down = true
    await s.syncNow()
    await s.close()
    const again = mk('sent-db')
    expect((await again.getPending())[0].sent).toBe(true)
  })

  it('reopens a dead IndexedDB connection and retries the write once', async () => {
    const s = mk()
    const h = (await (s as unknown as { db(): Promise<{ close(): void }> }).db())
    h.close() // simulates iOS killing the connection
    const op = await add(s)
    expect((await s.getPending()).map((x) => x.client_op_id)).toEqual([op.client_op_id])
  })

  it('enqueueOp rejects (never reports success) when the write cannot be made', async () => {
    const s = mk()
    ;(s as unknown as { writeOp: () => Promise<void> }).writeOp = () => Promise.reject(new Error('disk full'))
    await expect(add(s)).rejects.toThrow('disk full')
  })

  it('pauses on 401 without backoff polling and resumes after login', async () => {
    const s = new OfflineStore({ dbName: `auth-${Math.random()}`, autoSync: true })
    stores.push(s)
    srv.state.unauth = true
    await add(s)
    await s.syncNow()
    expect(s.getStatus().error).toBe('unauthorized')
    const calls = (fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length
    await new Promise((r) => setTimeout(r, 1300)) // > first backoff step
    expect((fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBe(calls)
    srv.state.unauth = false
    await s.resume()
    expect((await s.getPending()).length).toBe(0)
    expect(s.getStatus().error).toBeNull()
  })

  it('ignores the stale total of a duplicate result', async () => {
    const s = mk()
    const op = await add(s)
    await s.syncNow()
    srv.totals.set('p1', 9) // another device changed things since
    await s.setMeta('cursor', null) // force a snapshot
    await s.syncNow({ pull: true })
    // replay of the same op id (e.g. restored from backup) returns a stale total of 1
    await s.enqueueOp({ type: 'add', barcode: '5701234567899', quantity: 1, client_op_id: op.client_op_id })
    await s.syncNow()
    const p = (await s.lookupBarcode('5701234567899')).product!
    expect(await s.displayedQuantity(p)).toBe(9)
  })

  it('household switch wipes local data including unsent ops; same household keeps them', async () => {
    const s = mk()
    const me = (hid: string) => ({ user: null, household: { id: hid, name: 'h' }, kiosk: true, settings: { scan_rearm_ms: 600 } }) as never
    await s.adoptSession(me('h1'))
    srv.state.down = true
    await add(s)
    await s.clearForLogout()
    expect((await s.getPending()).length).toBe(1) // logout keeps unsent ops
    expect(await s.getMe()).toBeUndefined()
    expect((await s.adoptSession(me('h1'))).droppedPending).toBe(0)
    expect((await s.getPending()).length).toBe(1)
    expect((await s.adoptSession(me('h2'))).droppedPending).toBe(1)
    expect((await s.getPending()).length).toBe(0)
  })

  it('retryFailedOp moves failed → pending atomically', async () => {
    const s = mk()
    const bad = await add(s)
    srv.state.rejectIds.add(bad.client_op_id)
    await s.syncNow()
    srv.state.rejectIds.clear()
    await s.retryFailedOp(bad.client_op_id)
    expect((await s.getFailedOps()).length).toBe(0)
    expect((await s.getPending()).map((x) => x.client_op_id)).toEqual([bad.client_op_id])
    await s.syncNow()
    expect(srv.totals.get('p1')).toBe(1)
  })
})
