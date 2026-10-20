// "The same item is never counted twice in succession": a scan whose normalised code equals the previously COUNTED
// scan (same mode, same scan session) is not counted; the user taps +1/+2/+5 for more. Resets when a different
// code is counted, the mode is switched, the scan session ends / a new one starts, or that last scan is undone.
import type { ScanMode } from './mode'

interface Last {
  code: string
  mode: ScanMode
  /** session the scan belongs to (null = none) */
  session: string | null
  opId: string
}

export class LastCounted {
  private last: Last | null = null

  /** True when this scan repeats the last counted one and must NOT be counted. `session` = current live session id or null. */
  isRepeat(code: string, mode: ScanMode, session: string | null): boolean {
    const l = this.last
    return !!l && l.code === code && l.mode === mode && l.session === session
  }

  /** A scan was counted (its op is durably enqueued). */
  record(code: string, mode: ScanMode, session: string | null, opId: string) {
    this.last = { code, mode, session, opId }
  }

  /** The op was undone: if it is the last counted scan, the same code counts again. */
  undone(opId: string) {
    if (this.last?.opId === opId) this.last = null
  }

  reset() {
    this.last = null
  }
}
