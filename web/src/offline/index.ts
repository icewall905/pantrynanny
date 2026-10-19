// Public interface of the offline layer. IndexedDB queue + foreground-driven sync.
import { useSyncExternalStore } from 'react'
import type { ClientOp, Me } from '../api/types'
import { OfflineStore, type NewOp } from './store'
import type { SyncStatus } from './types'

export type { NewOp, SyncStatus }
export { OfflineStore } from './store'
export { normalizeBarcode, gtinChecksumValid } from './normalize'
export type * from './types'

let _store: OfflineStore | null = null
/** Process-wide store (one IndexedDB database per origin). */
export function getStore(): OfflineStore {
  _store ??= new OfflineStore()
  return _store
}

/** Queue an inventory operation. Resolves once it is durably stored locally (not when synced). */
export function enqueueOp(op: NewOp): Promise<ClientOp> {
  return getStore().enqueueOp(op)
}

/** Resume sync after login/pairing (sync pauses itself on 401). */
export function resumeSync() {
  return getStore().resume()
}
export const adoptSession = (me: Me) => getStore().adoptSession(me)
export const clearLocalData = () => getStore().clearForLogout()
export { uuid } from './uuid'

export function syncNow(opts?: { pull?: boolean }): Promise<void> {
  return getStore().syncNow(opts)
}

/** Start foreground-driven sync (online/visibility events, 30 s push, 60 s pull). Idempotent. */
export function startSync() {
  getStore().start()
}

export function useSyncStatus(): SyncStatus {
  const s = getStore()
  return useSyncExternalStore(s.subscribeStatus, s.getStatus, s.getStatus)
}

/**
 * Register the PWA service worker (autoUpdate) and check for a new version hourly. With
 * `autoUpdate` + skipWaiting the new worker activates on its own; the scanner page reloads itself
 * (the plugin reloads the page); ScanPage then resumes scanning without a tap when the camera
 * permission is already granted (best effort, see ScanPage).
 */
let swDone = false
export async function registerServiceWorker() {
  if (swDone || typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
  swDone = true
  try {
    const { registerSW } = await import('virtual:pwa-register')
    registerSW({
      immediate: true,
      onRegisteredSW: (_url, reg) => {
        if (reg) setInterval(() => void reg.update().catch(() => undefined), 60 * 60 * 1000)
      },
    })
  } catch {
    /* dev mode / unsupported */
  }
}
