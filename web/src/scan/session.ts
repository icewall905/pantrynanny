// Scan sessions: every run of scans is grouped automatically (no start button, no extra taps). A
// session starts with the first scan and ends after a pause or when the scanner is closed; the
// summary then shows what changed and which barcodes still need a name.

import type { ScanMode } from './mode'

export const SESSION_IDLE_MS = 10 * 60_000
const KEY = 'pn.scan.sessions'
const KEEP = 10

export interface SessionLine {
  barcode: string
  name: string | null
  unknown: boolean
  added: number
  removed: number
}

export interface ScanSession {
  id: string
  startedAt: number
  lastAt: number
  scans: number
  added: number
  removed: number
  lines: Record<string, SessionLine>
  /** op id -> what it did, so undo can be subtracted again */
  ops: Record<string, { barcode: string; type: ScanMode; qty: number }>
}

export interface ScanRecord {
  opId: string
  at: number
  type: ScanMode
  qty: number
  barcode: string
  name: string | null
  unknown: boolean
}

export function expired(s: ScanSession | null, now: number, idleMs = SESSION_IDLE_MS): boolean {
  return !s || now - s.lastAt > idleMs
}

/** Pure: returns the session after this scan. A new one starts when there is none or it went idle. */
export function recordScan(s: ScanSession | null, r: ScanRecord, idleMs = SESSION_IDLE_MS): ScanSession {
  const base: ScanSession = expired(s, r.at, idleMs)
    ? { id: `s${r.at.toString(36)}`, startedAt: r.at, lastAt: r.at, scans: 0, added: 0, removed: 0, lines: {}, ops: {} }
    : s!
  const prev = base.lines[r.barcode] ?? { barcode: r.barcode, name: null, unknown: true, added: 0, removed: 0 }
  const line: SessionLine = {
    ...prev,
    name: r.name ?? prev.name,
    unknown: r.unknown && prev.unknown,
    added: prev.added + (r.type === 'add' ? r.qty : 0),
    removed: prev.removed + (r.type === 'remove' ? r.qty : 0),
  }
  return {
    ...base,
    lastAt: r.at,
    scans: base.scans + 1,
    added: base.added + (r.type === 'add' ? r.qty : 0),
    removed: base.removed + (r.type === 'remove' ? r.qty : 0),
    lines: { ...base.lines, [r.barcode]: line },
    ops: { ...base.ops, [r.opId]: { barcode: r.barcode, type: r.type, qty: r.qty } },
  }
}

/** Pure: the session with an undone op taken back out (no-op for ops from elsewhere). */
export function recordUndo(s: ScanSession | null, opId: string): ScanSession | null {
  const op = s?.ops[opId]
  if (!s || !op) return s
  const { [opId]: _gone, ...ops } = s.ops
  const line = s.lines[op.barcode]
  const add = op.type === 'add' ? op.qty : 0
  const rem = op.type === 'remove' ? op.qty : 0
  const lines = { ...s.lines }
  const next = line && { ...line, added: line.added - add, removed: line.removed - rem }
  if (next && (next.added > 0 || next.removed > 0)) lines[op.barcode] = next
  else delete lines[op.barcode]
  return { ...s, scans: s.scans - 1, added: s.added - add, removed: s.removed - rem, lines, ops }
}

/** Fill in names that were looked up after the scan. */
export function nameLine(s: ScanSession | null, barcode: string, name: string, unknown: boolean): ScanSession | null {
  const line = s?.lines[barcode]
  if (!s || !line) return s
  return { ...s, lines: { ...s.lines, [barcode]: { ...line, name, unknown: line.unknown && unknown } } }
}

export function summarize(s: ScanSession) {
  const lines = Object.values(s.lines)
  return {
    durationMs: s.lastAt - s.startedAt,
    products: lines.length,
    unknown: lines.filter((l) => l.unknown),
    lines: lines.sort((a, b) => b.added + b.removed - (a.added + a.removed)),
  }
}

export function loadSessions(storage: Pick<Storage, 'getItem'> | null = safeStorage()): ScanSession[] {
  try {
    const v = JSON.parse(storage?.getItem(KEY) ?? '[]')
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}

/** Keep finished sessions on this device for the review list (newest first). Empty ones are dropped. */
export function saveSession(s: ScanSession, storage: Pick<Storage, 'getItem' | 'setItem'> | null = safeStorage()) {
  if (s.scans <= 0) return
  const rest = loadSessions(storage).filter((x) => x.id !== s.id)
  try {
    storage?.setItem(KEY, JSON.stringify([{ ...s, ops: {} }, ...rest].slice(0, KEEP)))
  } catch {
    /* storage full or blocked: the summary was still shown */
  }
}

function safeStorage(): Storage | null {
  try {
    return localStorage
  } catch {
    return null
  }
}
