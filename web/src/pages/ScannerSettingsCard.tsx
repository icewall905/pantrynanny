import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ScanLine } from 'lucide-react'
import { Card, Toggle } from '../components/ui'
import { loadScanPrefs, saveScanPrefs, type ScanPrefs } from '../scan/prefs'
import DirectScannerLink from './DirectScannerLink'
import { loadSessions, summarize } from '../scan/session'

/** Device-local scanner set-up plus the last scan sessions on this device. */
export default function ScannerSettingsCard() {
  const { t, i18n } = useTranslation()
  const [prefs, setPrefs] = useState<ScanPrefs>(loadScanPrefs)
  const [sessions] = useState(() => loadSessions())
  const set = (p: Partial<ScanPrefs>) => {
    const next = { ...prefs, ...p }
    saveScanPrefs(next)
    setPrefs(next)
  }
  return (
    <Card>
      <h2 className="mb-1 flex items-center gap-2 text-lg font-bold">
        <ScanLine className="size-5 text-leaf-600" /> {t('scanner.title')}
      </h2>
      <p className="mb-3 text-sm text-ink-500">{t('scanner.hint')}</p>
      <Toggle checked={prefs.hid} onChange={(v) => set({ hid: v })} label={t('scanner.hid')} hint={t('scanner.hidHint')} />
      <Toggle checked={prefs.camera} onChange={(v) => set({ camera: v })} label={t('scanner.camera')} hint={t('scanner.cameraHint')} />
      <Toggle checked={prefs.quantity} onChange={(v) => set({ quantity: v })} label={t('scanner.quantity')} hint={t('scanner.quantityHint')} />
      <div className="mt-4">
        <DirectScannerLink />
      </div>
      <h3 className="mb-1 mt-4 text-sm font-semibold text-ink-700">{t('scanner.sessions')}</h3>
      {sessions.length === 0 ? (
        <p className="text-sm text-ink-500">{t('scanner.noSessions')}</p>
      ) : (
        <ul className="divide-y divide-cream-200 text-sm" data-testid="scan-sessions">
          {sessions.map((s) => {
            const sum = summarize(s)
            return (
              <li key={s.id} className="flex flex-wrap items-baseline gap-x-3 py-2">
                <span className="font-medium">
                  {new Date(s.startedAt).toLocaleString(i18n.language, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
                </span>
                <span className="text-ink-500">{t('scanner.sessionMeta', { scans: s.scans, products: sum.products })}</span>
                <span className="font-semibold text-leaf-600">+{s.added}</span>
                <span className="font-semibold text-tomato-600">−{s.removed}</span>
                {sum.unknown.length > 0 && <span className="text-honey-600">{t('scanner.sessionUnknown', { count: sum.unknown.length })}</span>}
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
