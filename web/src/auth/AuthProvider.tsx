import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, useLocation } from 'react-router-dom'
import { ApiError, get, post } from '../api/client'
import type { HouseholdSettings, Me } from '../api/types'
import { keys } from '../api/queries'
import { ErrorState, Spinner } from '../components/ui'
import { setLocale } from '../i18n'
import { adoptSession, clearLocalData, resumeSync } from '../offline'

interface AuthCtx {
  me: Me | null
  loading: boolean
  isAdmin: boolean
  login: (username: string, password: string, remember: boolean) => Promise<Me>
  logout: () => Promise<void>
}
const Ctx = createContext<AuthCtx | null>(null)

export const DEFAULT_SETTINGS: HouseholdSettings = {
  locale: 'da',
  allow_negative_stock: false,
  expiry_soon_days: 3,
  auto_shopping_low_stock: true,
  remove_mode_timeout_min: 10,
  scan_rearm_ms: 600,
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: keys.me,
    queryFn: async () => {
      try {
        return await get<Me>('/auth/me')
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    retry: false,
    staleTime: 5 * 60_000,
  })

  useEffect(() => {
    const onUnauth = () => qc.setQueryData(keys.me, null)
    window.addEventListener('pn:unauthorized', onUnauth)
    return () => window.removeEventListener('pn:unauthorized', onUnauth)
  }, [qc])

  // Household locale applies only when this device has no explicit preference.
  const hasStored = (() => {
    try {
      return !!localStorage.getItem('pn.locale')
    } catch {
      return true
    }
  })()
  const householdLocale = q.data?.settings.locale
  useEffect(() => {
    if (householdLocale && !hasStored) setLocale(householdLocale)
  }, [householdLocale, hasStored])

  const login = useCallback<AuthCtx['login']>(
    async (username, password, remember) => {
      const me = await post<Me>('/auth/login', { username, password, remember })
      qc.setQueryData(keys.me, me)
      void adoptSession(me)
        .catch(() => undefined)
        .finally(() => void resumeSync()) // household switch wipes local data; lift sync pause
      return me
    },
    [qc],
  )
  const logout = useCallback(async () => {
    try {
      await post('/auth/logout')
    } finally {
      qc.clear()
      qc.setQueryData(keys.me, null)
      void clearLocalData()
    }
  }, [qc])

  const me = q.data ?? null
  const value = useMemo<AuthCtx>(
    () => ({ me, loading: q.isLoading, isAdmin: me?.user?.role === 'admin' || me?.user?.role === 'owner', login, logout }),
    [me, q.isLoading, login, logout],
  )
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error('useAuth outside AuthProvider')
  return c
}

export function useSettings(): HouseholdSettings {
  return useContext(Ctx)?.me?.settings ?? DEFAULT_SETTINGS
}

/** Guards authenticated routes. Kiosk sessions may only use /scan. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth()
  const loc = useLocation()
  if (loading) return <Spinner />
  if (!me) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />
  if (me.kiosk) return <Navigate to="/scan" replace />
  return <>{children}</>
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { isAdmin } = useAuth()
  if (!isAdmin) return <Navigate to="/" replace />
  return <>{children}</>
}
