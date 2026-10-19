import { describe, expect, it } from 'vitest'
import { encodeEan13, encodeEan8, renderLuma } from './eanEncode'
import { ZxingDecoderCore } from './zxingCore'

describe('ZxingDecoderCore', () => {
  const core = new ZxingDecoderCore()
  it('decodes EAN-13', () => {
    const { luma, width, height } = renderLuma(encodeEan13('5701234567899'), 3, 120)
    expect(core.decode(luma, width, height)).toEqual([{ rawValue: '5701234567899', format: 'ean_13' }])
  })
  it('decodes EAN-8 at small scale', () => {
    const { luma, width, height } = renderLuma(encodeEan8('96385074'), 2, 100)
    expect(core.decode(luma, width, height)[0]).toMatchObject({ rawValue: '96385074', format: 'ean_8' })
  })
  it('returns [] when there is no barcode', () => {
    expect(core.decode(new Uint8ClampedArray(200 * 100).fill(200), 200, 100)).toEqual([])
  })
})
