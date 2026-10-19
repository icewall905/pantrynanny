// Registers the `scan` i18next namespace (kept out of i18n/index.ts on purpose).
import i18n from 'i18next'
import da from '../i18n/scan.da.json'
import en from '../i18n/scan.en.json'

export const NS = 'scan'
let done = false
export function registerScanI18n() {
  if (done) return
  done = true
  i18n.addResourceBundle('da', NS, da, true, true)
  i18n.addResourceBundle('en', NS, en, true, true)
}
registerScanI18n()
