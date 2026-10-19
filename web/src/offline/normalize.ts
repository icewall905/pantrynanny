// Barcode normalisation – TypeScript port of docs/api-contract.md §6.

export type Symbology =
  | 'ean_13'
  | 'ean_8'
  | 'upc_a'
  | 'upc_e'
  | 'code_128'
  | 'code_39'
  | 'itf'
  | 'qr'
  | 'data_matrix'
  | 'other'

export interface NormalizedBarcode {
  code: string
  symbology: string
  valid: boolean
}

/** GS1 mod-10 check: last digit is the check digit. */
export function gtinChecksumValid(digits: string): boolean {
  if (!/^\d{8,14}$/.test(digits)) return false
  return gs1CheckDigit(digits.slice(0, -1)) === Number(digits[digits.length - 1])
}

/** Check digit for a payload (digits without the check digit). */
export function gs1CheckDigit(payload: string): number {
  let sum = 0
  for (let i = 0; i < payload.length; i++) {
    const d = Number(payload[payload.length - 1 - i])
    sum += i % 2 === 0 ? d * 3 : d
  }
  return (10 - (sum % 10)) % 10
}

const SYMBOLOGIES = new Set<string>(['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr', 'data_matrix', 'other'])
const NON_GTIN = new Set<string>(['qr', 'data_matrix', 'code_128', 'code_39'])

/** Expand a 6-digit UPC-E body to a 12-digit UPC-A (with check digit). Mirrors backend expand_upc_e. */
function expandUpcE(six: string, ns: string): string {
  const d = six
  const last = d[5]
  let body: string
  if ('012'.includes(last)) body = d.slice(0, 2) + last + '0000' + d.slice(2, 5)
  else if (last === '3') body = d.slice(0, 3) + '00000' + d.slice(3, 5)
  else if (last === '4') body = d.slice(0, 4) + '00000' + d[4]
  else body = d.slice(0, 5) + '0000' + last
  body = ns + body
  return body + gs1CheckDigit(body)
}

/** Exact port of backend/pantrynanny/services/barcodes.py `normalize` (keep in parity). */
export function normalizeBarcode(raw: string, symbologyHint?: string | null): NormalizedBarcode {
  const stripped = raw.trim()
  const hint = symbologyHint && SYMBOLOGIES.has(symbologyHint) ? symbologyHint : null
  const local = (): NormalizedBarcode => ({ code: `local:${stripped}`, symbology: hint ?? 'other', valid: false })
  if (hint && NON_GTIN.has(hint)) return local()

  const digits = stripped.replace(/\s+/g, '')
  if (!/^\d+$/.test(digits)) return local()

  const n = digits.length
  if (n === 6 || (n === 8 && hint === 'upc_e')) {
    let upcA: string
    if (n === 6) upcA = expandUpcE(digits, '0')
    else {
      if (digits[0] !== '0' && digits[0] !== '1') return local()
      upcA = expandUpcE(digits.slice(1, 7), digits[0])
      if (upcA[11] !== digits[7]) return local()
    }
    return { code: upcA.padStart(14, '0'), symbology: 'upc_e', valid: true }
  }

  const kinds: Record<number, string> = { 8: 'ean_8', 12: 'upc_a', 13: 'ean_13', 14: 'itf' }
  if (!(n in kinds) || !gtinChecksumValid(digits)) return local()

  if (n === 13 && /^2\d/.test(digits)) return { code: `instore:${digits.slice(0, 7)}`, symbology: 'ean_13', valid: true }
  return { code: digits.padStart(14, '0'), symbology: kinds[n], valid: true }
}
