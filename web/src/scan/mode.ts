// ADD / REMOVE mode persistence and the REMOVE safety timeout.
export type ScanMode = 'add' | 'remove'
const KEY = 'pn.scan.mode'

/** REMOVE never survives a reload: the page always starts in ADD. */
export function loadMode(storage: Pick<Storage, 'getItem' | 'setItem'> | null = safeStorage()): ScanMode {
  try {
    const v = storage?.getItem(KEY)
    if (v === 'remove') storage?.setItem(KEY, 'add')
  } catch {
    /* ignore */
  }
  return 'add'
}

export function saveMode(mode: ScanMode, storage: Pick<Storage, 'getItem' | 'setItem'> | null = safeStorage()) {
  try {
    storage?.setItem(KEY, mode)
  } catch {
    /* ignore */
  }
}

/** True when REMOVE has been idle long enough to fall back to ADD. */
export function removeTimedOut(mode: ScanMode, lastActivityAt: number, now: number, timeoutMin: number): boolean {
  return mode === 'remove' && now - lastActivityAt >= Math.max(1, timeoutMin) * 60_000
}

function safeStorage(): Storage | null {
  try {
    return localStorage
  } catch {
    return null
  }
}
