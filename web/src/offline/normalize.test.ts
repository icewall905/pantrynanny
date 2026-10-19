import { describe, expect, it } from 'vitest'
import { gs1CheckDigit, gtinChecksumValid, normalizeBarcode } from './normalize'

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
    expect(normalizeBarcode('2012345678905', 'ean_13')).toMatchObject({ code: 'instore:2012345', valid: true })
    expect(normalizeBarcode('2012345999999').code).toBe('instore:2012345')
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
