import { describe, expect, it } from 'vitest'
import { EmptyBarcodeError, gs1CheckDigit, gtinChecksumValid, isBlankBarcode, normalizeBarcode, stripBarcode } from './normalize'

describe('normalizeBarcode', () => {
  it('pads EAN-13 to GTIN-14', () => {
    expect(normalizeBarcode('5701234567899', 'ean_13')).toEqual({ code: '05701234567899', symbology: 'ean_13', valid: true })
  })
  it('handles EAN-8, UPC-A', () => {
    expect(normalizeBarcode('96385074').code).toBe('00000096385074')
    expect(normalizeBarcode('036000291452').code).toBe('00036000291452')
    expect(normalizeBarcode('036000291452').symbology).toBe('upc_a')
  })
  it('strips whitespace', () => {
    expect(normalizeBarcode(' 5701234567899\n').code).toBe('05701234567899')
  })
  it('accepts GTIN-14', () => {
    const p = '1570123456789'
    const code = p + gs1CheckDigit(p)
    expect(normalizeBarcode(code).code).toBe(code)
  })
  it('expands UPC-E', () => {
    expect(normalizeBarcode('04252614', 'upc_e').code).toBe('00042100005264')
    expect(normalizeBarcode('425261').code).toBe('00042100005264')
    expect(normalizeBarcode('04252615', 'upc_e').valid).toBe(false)
  })
  it('maps in-store 20-29 prefix to item reference', () => {
    expect(normalizeBarcode('2012345678903', 'ean_13')).toMatchObject({ code: 'instore:2012345', valid: true })
  })
  it('falls back to local: for bad checksum, QR, code128', () => {
    expect(normalizeBarcode('5701234567893')).toMatchObject({ code: 'local:5701234567893', valid: false })
    expect(normalizeBarcode('HELLO-123', 'code_128')).toMatchObject({ code: 'local:HELLO-123', valid: false, symbology: 'code_128' })
    expect(normalizeBarcode('1234567').code).toBe('local:1234567')
  })
  it('checksum helpers', () => {
    expect(gtinChecksumValid('5701234567899')).toBe(true)
    expect(gtinChecksumValid('5701234567891')).toBe(false)
    expect(gtinChecksumValid('abc')).toBe(false)
  })
})

// Expected values computed with backend/pantrynanny/services/barcodes.py normalize().
const PARITY: [string, string | null, string, string, boolean][] = [
  ['5701234567899', 'ean_13', '05701234567899', 'ean_13', true],
  ['96385074', null, '00000096385074', 'ean_8', true],
  ['036000291452', null, '00036000291452', 'upc_a', true],
  [' 5701234567899\n', null, '05701234567899', 'ean_13', true],
  ['15701234567894', null, 'local:15701234567894', 'other', false],
  ['15701234567896', null, '15701234567896', 'itf', true],
  ['04252614', 'upc_e', '00042100005264', 'upc_e', true],
  ['425261', null, '00042100005264', 'upc_e', true],
  ['04252615', 'upc_e', 'local:04252615', 'upc_e', false],
  ['2012345678903', 'ean_13', 'instore:2012345', 'ean_13', true],
  ['2900000123458', null, 'instore:2900000', 'ean_13', true],
  ['2012345678905', 'ean_13', 'local:2012345678905', 'ean_13', false],
  ['2012345999999', null, 'local:2012345999999', 'other', false],
  ['5701234567893', null, 'local:5701234567893', 'other', false],
  ['HELLO-123', 'code_128', 'local:HELLO-123', 'code_128', false],
  ['1234567', null, 'local:1234567', 'other', false],
  [' 12345678 ', 'qr', 'local:12345678', 'qr', false],
  ['5701234567899', 'code_39', 'local:5701234567899', 'code_39', false],
  ['  abc ', 'bogus', 'local:abc', 'other', false],
  ['5701 2345 67899', null, '05701234567899', 'ean_13', true],
  ['96385074', 'upc_e', 'local:96385074', 'upc_e', false],
  ['5701234567899', 'ean_8', '05701234567899', 'ean_13', true],
  ['2012345678905', 'other', 'local:2012345678905', 'other', false],
]

describe('backend parity', () => {
  it.each(PARITY)('%j hint=%s', (raw, hint, code, symbology, valid) => {
    expect(normalizeBarcode(raw, hint)).toEqual({ code, symbology, valid })
  })
})

// Strip rule (both ends only): ASCII whitespace, U+001C-001F, U+0085, U+00A0, U+FEFF; digits are ASCII [0-9].
const STRIP_PARITY: [string, string | null, string, string, boolean][] = [
  ['5701234567899\x1d', null, '05701234567899', 'ean_13', true],
  ['\x1d5701234567899\x1c\x1e\x1f', null, '05701234567899', 'ean_13', true],
  ['\ufeff5701234567899', null, '05701234567899', 'ean_13', true],
  ['\u00a05701234567899\u0085', null, '05701234567899', 'ean_13', true],
  ['\v\f5701234567899\t\r\n', null, '05701234567899', 'ean_13', true],
  ['570123456789\u00b2', null, 'local:570123456789\u00b2', 'other', false],
  ['\uff15\uff17\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19\uff19', null, 'local:\uff15\uff17\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19\uff19', 'other', false],
  ['\u0665\u0667', null, 'local:\u0665\u0667', 'other', false],
  ['\u200b5701234567899', null, 'local:\u200b5701234567899', 'other', false], // zero-width space is not stripped
  ['\x1dAB-12\x1d', 'code_128', 'local:AB-12', 'code_128', false],
]

describe('strip rule parity', () => {
  it.each(STRIP_PARITY)('%j hint=%s', (raw, hint, code, symbology, valid) => {
    expect(normalizeBarcode(raw, hint)).toEqual({ code, symbology, valid })
  })
  it('strips exactly the specified set from both ends only', () => {
    expect(stripBarcode(' \t\n\r\v\f\x1c\x1d\x1e\x1f\x85\xa0\ufeffabc\ufeff\xa0\x85\x1f ')).toBe('abc')
    expect(stripBarcode('a\x1db')).toBe('a\x1db')
    expect(stripBarcode('\x1b x\x1b')).toBe('\x1b x\x1b') // ESC is not stripped; inner space untouched by strip
  })
  it('empty after stripping is invalid', () => {
    for (const raw of ['', '   ', '\x1d', '\ufeff\xa0\x85\t']) {
      expect(isBlankBarcode(raw)).toBe(true)
      expect(() => normalizeBarcode(raw)).toThrow(EmptyBarcodeError)
    }
    expect(isBlankBarcode('0')).toBe(false)
  })
})
