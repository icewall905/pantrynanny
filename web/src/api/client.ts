// Minimal fetch wrapper. Cookie session auth + CSRF header (see docs/api-contract.md §1).

export class ApiError extends Error {
  status: number
  code: string | null
  body: unknown
  constructor(status: number, message: string, code: string | null, body: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.body = body
  }
}

/** True when the request never reached the server (offline, DNS, server down). */
export function isNetworkError(e: unknown): boolean {
  return e instanceof TypeError || (e instanceof ApiError && e.status >= 502 && e.status <= 504)
}

type Json = Record<string, unknown> | unknown[]

export interface RequestOptions {
  method?: string
  body?: Json | FormData
  headers?: Record<string, string>
  signal?: AbortSignal
  timeoutMs?: number
  /** Do not broadcast `pn:unauthorized` on 401 (background sync handles it itself). */
  silent401?: boolean
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = (opts.method ?? (opts.body ? 'POST' : 'GET')).toUpperCase()
  const headers: Record<string, string> = { Accept: 'application/json', ...opts.headers }
  if (method !== 'GET' && method !== 'HEAD') headers['X-PN-CSRF'] = '1'
  let body: BodyInit | undefined
  if (opts.body instanceof FormData) body = opts.body
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }

  const ctrl = new AbortController()
  const timer = opts.timeoutMs ? setTimeout(() => ctrl.abort(), opts.timeoutMs) : null
  opts.signal?.addEventListener('abort', () => ctrl.abort())
  try {
    const res = await fetch(`/api${path}`, {
      method,
      headers,
      body,
      credentials: 'same-origin',
      signal: ctrl.signal,
    })
    if (res.status === 204) return undefined as T
    const ct = res.headers.get('content-type') ?? ''
    const data: unknown = ct.includes('application/json') ? await res.json() : await res.text()
    if (!res.ok) {
      const d = data as { detail?: unknown; code?: string } | string
      const msg =
        typeof d === 'object' && d && typeof d.detail === 'string' ? d.detail : res.statusText
      const code = typeof d === 'object' && d ? (d.code ?? null) : null
      if (res.status === 401 && !opts.silent401) window.dispatchEvent(new CustomEvent('pn:unauthorized'))
      throw new ApiError(res.status, msg, code, data)
    }
    return data as T
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw new TypeError('timeout')
    throw e
  } finally {
    if (timer) clearTimeout(timer)
  }
}

export const get = <T>(path: string, opts?: RequestOptions) => api<T>(path, { ...opts, method: 'GET' })
export const post = <T>(path: string, body?: Json | FormData, opts?: RequestOptions) =>
  api<T>(path, { ...opts, method: 'POST', body })
export const patch = <T>(path: string, body: Json, opts?: RequestOptions) =>
  api<T>(path, { ...opts, method: 'PATCH', body })
export const del = <T>(path: string, opts?: RequestOptions) => api<T>(path, { ...opts, method: 'DELETE' })

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}
