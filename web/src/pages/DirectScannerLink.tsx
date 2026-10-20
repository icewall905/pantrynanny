import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Copy, Link2 } from 'lucide-react'
import { Button } from '../components/ui'
import { buildScanLink, type ScanLinkVariant } from '../scan/link'

const VARIANTS: { key: string; v: ScanLinkVariant }[] = [
  { key: 'add', v: {} },
  { key: 'remove', v: { mode: 'remove' } },
  { key: 'handOnly', v: { cameraOff: true } },
]

/** "Direct scanner link": bookmark / Home-Screen URL that opens /scan straight into scanning. */
export default function DirectScannerLink() {
  const { t } = useTranslation()
  const [copied, setCopied] = useState<string | null>(null)
  const copy = async (key: string, url: string) => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(key)
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 2000)
    } catch {
      /* clipboard unavailable: the URL is selectable in the field */
    }
  }
  return (
    <div data-testid="direct-scanner-link">
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold text-ink-700">
        <Link2 className="size-4 text-leaf-600" /> {t('scanner.link.title')}
      </h3>
      <p className="mb-2 text-sm text-ink-500">{t('scanner.link.hint')}</p>
      <ul className="space-y-2">
        {VARIANTS.map(({ key, v }) => {
          const url = buildScanLink(window.location.origin, v)
          return (
            <li key={key}>
              <div className="text-xs font-medium text-ink-500">{t(`scanner.link.${key}`)}</div>
              <div className="flex items-center gap-2">
                <input
                  readOnly
                  value={url}
                  onFocus={(e) => e.currentTarget.select()}
                  aria-label={t(`scanner.link.${key}`)}
                  className="min-w-0 flex-1 rounded-lg border border-cream-200 bg-cream-50 px-2 py-1.5 font-mono text-xs"
                />
                <Button size="sm" onClick={() => void copy(key, url)} data-testid={`copy-link-${key}`}>
                  {copied === key ? <Check className="size-4" /> : <Copy className="size-4" />} {copied === key ? t('scanner.link.copied') : t('scanner.link.copy')}
                </Button>
              </div>
            </li>
          )
        })}
      </ul>
      <p className="mt-2 text-xs text-ink-500">{t('scanner.link.ipad')}</p>
    </div>
  )
}
