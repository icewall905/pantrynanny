import type { i18n as I18n, TFunction } from 'i18next'
import { ApiError } from '../api/client'

const KNOWN = new Set([
  'invalid_quantity',
  'product_not_found',
  'location_not_found',
  'already_undone',
  'cannot_undo_undo',
  'clamped',
  'server_error',
  'bad_request',
  'location_not_empty',
  'default_location',
  'default_required',
  'last_owner',
  'cannot_delete_self',
  'owner_required',
  'username_taken',
  'invalid_merge',
  'category_not_found',
  'invalid_image',
  'payload_too_large',
  'rate_limited',
])

/** Friendly text for a server error_code, or null when unknown. */
export function codeText(t: TFunction, code: string | null | undefined): string | null {
  return code && KNOWN.has(code) ? t(`opError.${code}`, { ns: 'translation' }) : null
}

/** Friendly text for a failed offline op (OpResult.error_code), falling back to the raw message. */
export function opErrorText(i18n: I18n, code: string | null | undefined, fallback: string): string {
  return codeText(i18n.t.bind(i18n) as TFunction, code) ?? fallback
}

/** Message for a failed API call: friendly by code, else the server detail for 4xx, else the fallback. */
export function apiErrorText(t: TFunction, e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const c = codeText(t, e.code)
    if (c) return c
    if (e.status >= 400 && e.status < 500 && e.status !== 401 && e.message) return e.message
  }
  return fallback
}
