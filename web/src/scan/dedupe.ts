// Duplicate-frame suppression – implements docs/api-contract.md §4 exactly.
import { gtinChecksumValid } from '../offline/normalize'

export interface DeduplicatorOptions {
  /** REMARM_MS: absence needed before the same code counts again. Clamped to 250–3000. */
  rearmMs?: number
  /** Window in which two reads of a checksum-invalid code confirm it. */
  confirmWindowMs?: number
  /** Tracked entries older than this are garbage-collected. */
  gcMs?: number
}

export const DEFAULT_REARM_MS = 600

export function clampRearm(ms: number | null | undefined): number {
  const v = typeof ms === 'number' && Number.isFinite(ms) ? ms : DEFAULT_REARM_MS
  return Math.min(3000, Math.max(250, v))
}

/**
 * Is a single read of this value trustworthy? EAN/UPC-length digit strings need a valid
 * mod-10 checksum; other symbologies (Code 128, ITF …) carry their own checksum which the
 * decoder already verified.
 */
export function readIsTrusted(value: string, format?: string | null): boolean {
  if (/^\d+$/.test(value) && [8, 12, 13, 14].includes(value.length)) {
    if (format === 'upc_e' && value.length === 8) return true // UPC-E: validated during expansion
    return gtinChecksumValid(value)
  }
  if (format === 'ean_13' || format === 'ean_8' || format === 'upc_a') return false
  return true
}

export class ScanDeduplicator {
  private rearm: number
  private confirmWindow: number
  private gc: number
  private tracked = new Map<string, number>() // code → lastSeenAt
  private unconfirmed = new Map<string, number>() // code → first read time

  constructor(opts: DeduplicatorOptions = {}) {
    this.rearm = clampRearm(opts.rearmMs)
    this.confirmWindow = opts.confirmWindowMs ?? 250
    this.gc = opts.gcMs ?? 10_000
  }

  setRearmMs(ms: number) {
    this.rearm = clampRearm(ms)
  }

  /** Forget everything (mode switch). */
  clear() {
    this.tracked.clear()
    this.unconfirmed.clear()
  }

  /**
   * Feed one decoded frame result. Returns true when the code must be counted now.
   * `trusted` = checksum valid (single read fires). Untrusted reads need a second read
   * within the confirm window.
   */
  onDetection(code: string, t: number, trusted: boolean): boolean {
    this.collect(t)
    const last = this.tracked.get(code)
    if (last !== undefined && t - last < this.rearm) {
      this.tracked.set(code, t) // held in view: keep it alive, do not fire
      return false
    }
    // absent long enough (or never seen) → a new item, if the read is believable
    if (!trusted) {
      const first = this.unconfirmed.get(code)
      if (first === undefined || t - first > this.confirmWindow) {
        this.unconfirmed.set(code, t)
        return false
      }
      this.unconfirmed.delete(code)
    }
    this.tracked.set(code, t)
    return true
  }

  private collect(t: number) {
    for (const [c, s] of this.tracked) if (t - s >= this.gc) this.tracked.delete(c)
    for (const [c, s] of this.unconfirmed) if (t - s >= this.gc) this.unconfirmed.delete(c)
  }
}
