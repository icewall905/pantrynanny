import { useTranslation } from 'react-i18next'
import { Download } from 'lucide-react'
import { Card, PageHeader } from '../components/ui'

const RESOURCES = ['inventory', 'shopping', 'expiring', 'products', 'transactions'] as const

export default function ExportPage() {
  const { t } = useTranslation()
  return (
    <>
      <PageHeader title={t('nav.export')} subtitle={t('export.hint')} />
      <div className="grid gap-3 sm:grid-cols-2">
        {RESOURCES.map((r) => (
          <Card key={r} className="flex items-center justify-between gap-3">
            <span className="font-bold">{t(`export.${r}`)}</span>
            <span className="flex gap-2">
              {(['csv', 'json'] as const).map((f) => (
                <a
                  key={f}
                  href={`/api/export/${r}.${f}`}
                  download
                  className="inline-flex min-h-11 items-center gap-1.5 rounded-xl bg-leaf-50 px-4 text-sm font-semibold text-leaf-700 hover:bg-leaf-100"
                >
                  <Download className="size-4" /> {f.toUpperCase()}
                </a>
              ))}
            </span>
          </Card>
        ))}
      </div>
    </>
  )
}
