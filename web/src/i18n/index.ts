import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import da from './da.json'
import en from './en.json'

const stored = (() => {
  try {
    return localStorage.getItem('pn.locale')
  } catch {
    return null
  }
})()

type Dict = Record<string, unknown>

// Scanner/offline ticket ships its own strings as scan.<lng>.json; merge them under "scan"
// (unless the file already has a top-level "scan" key).
const scanFiles = import.meta.glob<Dict>('./scan.*.json', { eager: true, import: 'default' })
function scanFor(lng: 'da' | 'en'): Dict {
  const d = scanFiles[`./scan.${lng}.json`]
  if (!d) return {}
  return 'scan' in d ? d : { scan: d }
}

void i18n.use(initReactI18next).init({
  resources: {
    da: { translation: { ...da, ...scanFor('da') } },
    en: { translation: { ...en, ...scanFor('en') } },
  },
  lng: stored ?? 'da',
  fallbackLng: 'da',
  interpolation: { escapeValue: false },
})

export function setLocale(lng: 'da' | 'en') {
  void i18n.changeLanguage(lng)
  document.documentElement.lang = lng
  try {
    localStorage.setItem('pn.locale', lng)
  } catch {
    /* ignore */
  }
}

export default i18n
