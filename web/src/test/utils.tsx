import type { ReactElement } from 'react'
import { cleanup, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import '../i18n'
import { afterEach, vi } from 'vitest'

afterEach(() => cleanup())
import { ToastProvider } from '../components/Toast'

export function renderApp(ui: ReactElement, route = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

type Handler = (url: URL, init: RequestInit) => unknown | Response
/** Test-only fetch mock: routes by "METHOD /path" (path without /api, no query). */
export function mockFetch(routes: Record<string, Handler | unknown>) {
  const calls: { method: string; path: string; body: unknown }[] = []
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), 'http://localhost')
    const method = (init.method ?? 'GET').toUpperCase()
    const path = url.pathname.replace(/^\/api/, '')
    calls.push({ method, path, body: typeof init.body === 'string' ? JSON.parse(init.body) : init.body })
    const h = routes[`${method} ${path}`]
    if (h === undefined) return new Response(JSON.stringify({ detail: 'nope' }), { status: 404, headers: { 'content-type': 'application/json' } })
    const out = typeof h === 'function' ? (h as Handler)(url, init) : h
    if (out instanceof Response) return out
    return new Response(JSON.stringify(out), { status: 200, headers: { 'content-type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fn)
  return calls
}

export const jsonError = (status: number, detail = 'err') =>
  new Response(JSON.stringify({ detail }), { status, headers: { 'content-type': 'application/json' } })

export const ME = {
  user: { id: 'u1', username: 'anna', display_name: 'Anna', role: 'admin' },
  household: { id: 'h1', name: 'Hjemmet' },
  kiosk: false,
  settings: { locale: 'da', allow_negative_stock: false, expiry_soon_days: 3, auto_shopping_low_stock: true, remove_mode_timeout_min: 10, scan_rearm_ms: 600 },
}
