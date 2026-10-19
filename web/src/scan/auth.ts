// Session helpers for the /scan route (kiosk pairing or username/password).
import { ApiError, isNetworkError, post } from '../api/client'
import type { Me } from '../api/types'
import { adoptSession, clearLocalData, getStore, resumeSync } from '../offline'

export type SessionCheck = { kind: 'ok'; me: Me; cached: boolean; droppedPending?: number } | { kind: 'unauth' } | { kind: 'offline-unknown' }

export async function checkSession(): Promise<SessionCheck> {
  const store = getStore()
  try {
    // Plain fetch: a 401 here is expected and must not trigger the app-wide "logged out" redirect.
    const res = await fetch('/api/auth/me', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
    if (res.status === 401 || res.status === 403) return { kind: 'unauth' }
    if (!res.ok) throw new TypeError(`status ${res.status}`)
    const me = (await res.json()) as Me
    const { droppedPending } = await adoptSession(me)
    return { kind: 'ok', me, cached: false, droppedPending }
  } catch {
    const me = await store.getMe().catch(() => undefined)
    return me ? { kind: 'ok', me, cached: true } : { kind: 'offline-unknown' }
  }
}

export type AuthError = 'invalid' | 'rate' | 'offline'

function toAuthError(e: unknown): AuthError {
  if (isNetworkError(e)) return 'offline'
  if (e instanceof ApiError && e.status === 429) return 'rate'
  return 'invalid'
}

async function finish(): Promise<Me> {
  const res = await checkSession()
  if (res.kind !== 'ok') throw new ApiError(401, 'session not established', null, null)
  void resumeSync() // sync pauses itself on 401; a fresh session lifts the pause
  return res.me
}

export async function pairKiosk(code: string): Promise<{ me: Me } | { error: AuthError }> {
  try {
    await post('/auth/kiosk', { code: code.trim().toUpperCase() })
    return { me: await finish() }
  } catch (e) {
    return { error: toAuthError(e) }
  }
}

export async function loginRemember(username: string, password: string): Promise<{ me: Me } | { error: AuthError }> {
  try {
    await post('/auth/login', { username, password, remember: true })
    return { me: await finish() }
  } catch (e) {
    return { error: toAuthError(e) }
  }
}

export async function logout() {
  try {
    await post('/auth/logout')
  } catch {
    /* ignore */
  }
  await clearLocalData() // cached catalogue/stock/cursor go; unsent ops stay for the same household
}
