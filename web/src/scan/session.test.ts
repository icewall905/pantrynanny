import { describe, expect, it } from 'vitest'
import { loadSessions, nameLine, recordScan, recordUndo, saveSession, summarize, type ScanRecord } from './session'

const rec = (o: Partial<ScanRecord>): ScanRecord => ({
  opId: Math.random().toString(36),
  at: 0,
  type: 'add',
  qty: 1,
  barcode: '5701234567899',
  name: 'Mælk',
  unknown: false,
  ...o,
})

describe('scan sessions', () => {
  it('groups scans and totals added/removed per product', () => {
    let s = recordScan(null, rec({ at: 1000 }))
    s = recordScan(s, rec({ at: 2000, qty: 5 }))
    s = recordScan(s, rec({ at: 3000, barcode: '111111', name: null, unknown: true }))
    s = recordScan(s, rec({ at: 4000, type: 'remove' }))
    expect(s.scans).toBe(4)
    expect(s.added).toBe(7)
    expect(s.removed).toBe(1)
    const sum = summarize(s)
    expect(sum.products).toBe(2)
    expect(sum.durationMs).toBe(3000)
    expect(sum.unknown.map((l) => l.barcode)).toEqual(['111111'])
    expect(sum.lines[0]).toMatchObject({ name: 'Mælk', added: 6, removed: 1 })
  })

  it('a long pause starts a new session', () => {
    const a = recordScan(null, rec({ at: 0 }))
    const b = recordScan(a, rec({ at: 11 * 60_000 }))
    expect(b.id).not.toBe(a.id)
    expect(b.scans).toBe(1)
  })

  it('undo subtracts the op again', () => {
    let s = recordScan(null, rec({ opId: 'a', at: 1 }))
    s = recordScan(s, rec({ opId: 'b', at: 2, qty: 2 }))
    const u = recordUndo(s, 'b')!
    expect(u.added).toBe(1)
    expect(u.lines['5701234567899'].added).toBe(1)
    const none = recordUndo(u, 'a')!
    expect(none.scans).toBe(0)
    expect(none.lines).toEqual({})
    expect(recordUndo(none, 'unknown-op')).toBe(none)
  })

  it('a late lookup names the line', () => {
    const s = recordScan(null, rec({ barcode: '42424242', name: null, unknown: true }))
    const n = nameLine(s, '42424242', 'Havregryn', false)!
    expect(summarize(n).unknown).toHaveLength(0)
    expect(n.lines['42424242'].name).toBe('Havregryn')
  })

  it('keeps the last sessions on the device, skipping empty ones', () => {
    const mem = new Map<string, string>()
    const storage = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) }
    saveSession(recordUndo(recordScan(null, rec({ opId: 'x' })), 'x')!, storage)
    expect(loadSessions(storage)).toEqual([])
    for (let i = 0; i < 12; i++) saveSession(recordScan(null, rec({ at: i * 1e9 })), storage)
    const all = loadSessions(storage)
    expect(all).toHaveLength(10)
    expect(all[0].startedAt).toBe(11e9)
  })
})
