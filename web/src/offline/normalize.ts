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

/** Expand a 6-digit zero-suppressed UPC-E body (number system 0) to an 11-digit UPC-A payload. */
function expandUpcE(ns: string, d: string): string {
  const [d1, d2, d3, d4, d5, d6] = d.split('')
  let body: string
  if ('012'.includes(d6)) body = `${d1}${d2}${d6}0000${d3}${d4}${d5}`
  else if (d6 === '3') body = `${d1}${d2}${d3}00000${d4}${d5}`
  else if (d6 === '4') body = `${d1}${d2}${d3}${d4}00000${d5}`
  else body = `${d1}${d2}${d3}${d4}${d5}0000${d6}`
  return ns + body
}

export function normalizeBarcode(raw: string, symbologyHint?: string | null): NormalizedBarcode {
  const s = raw.replace(/\s+/g, '')
  const hint = symbologyHint ?? null
  const local = (): NormalizedBarcode => ({ code: `local:${raw}`, symbology: hint ?? 'other', valid: false })
  if (!/^\d+$/.test(s)) return local()

  let digits = s
  let sym = hint
  if (s.length === 6 || (s.length === 8 && hint === 'upc_e')) {
    const ns = s.length === 8 ? s[0] : '0'
    const body = s.length === 8 ? s.slice(1, 7) : s
    if (ns !== '0' && ns !== '1') return local()
    const payload = expandUpcE(ns, body)
    const full = payload + gs1CheckDigit(payload)
    if (s.length === 8 && Number(s[7]) !== Number(full[11])) return local()
    digits = full
    sym = 'upc_e'
  } else if (![8, 12, 13, 14].includes(s.length)) {
    return local()
  } else if (!sym || sym === 'other') {
    sym = s.length === 8 ? 'ean_8' : s.length === 12 ? 'upc_a' : s.length === 13 ? 'ean_13' : 'other'
  }

  if (digits.length === 13 && /^2\d/.test(digits)) {
    return { code: `instore:${digits.slice(0, 7)}`, symbology: sym ?? 'ean_13', valid: true }
  }
  if (!gtinChecksumValid(digits)) return local()
  return { code: digits.padStart(14, '0'), symbology: sym ?? 'other', valid: true }
}
