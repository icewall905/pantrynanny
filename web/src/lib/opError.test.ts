import { describe, expect, it } from 'vitest'
import i18n from '../i18n'
import { ApiError } from '../api/client'
import { apiErrorText, opErrorText } from './opError'

describe('opError', () => {
  it('maps OpResult error codes to friendly Danish and English text', async () => {
    for (const c of ['invalid_quantity', 'product_not_found', 'location_not_found', 'already_undone', 'clamped']) {
      await i18n.changeLanguage('da')
      const da = opErrorText(i18n, c, 'raw')
      await i18n.changeLanguage('en')
      const en = opErrorText(i18n, c, 'raw')
      expect(da).not.toBe('raw')
      expect(en).not.toBe('raw')
      expect(da).not.toBe(en)
    }
    await i18n.changeLanguage('da')
    expect(opErrorText(i18n, 'something_else', 'raw')).toBe('raw')
    expect(opErrorText(i18n, null, 'raw')).toBe('raw')
  })
  it('apiErrorText prefers the code text, then 4xx detail, then the fallback', () => {
    const t = i18n.t.bind(i18n)
    expect(apiErrorText(t, new ApiError(409, 'x', 'already_undone', {}), 'fb')).toBe('Allerede fortrudt')
    expect(apiErrorText(t, new ApiError(422, 'Bad name', null, {}), 'fb')).toBe('Bad name')
    expect(apiErrorText(t, new ApiError(500, 'boom', null, {}), 'fb')).toBe('fb')
  })
})
