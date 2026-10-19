import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { LogOut } from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'
import { setLocale } from '../i18n'
import { Button, Card, Chip, PageHeader } from '../components/ui'

export default function SettingsPage() {
  const { t, i18n } = useTranslation()
  const { me, logout, isAdmin } = useAuth()
  const lang = i18n.language.startsWith('en') ? 'en' : 'da'
  return (
    <>
      <PageHeader title={t('nav.settings')} />
      <div className="space-y-4">
        <Card>
          <h2 className="mb-1 text-lg font-bold">{t('settings.language')}</h2>
          <p className="mb-3 text-sm text-ink-500">{t('settings.languageHint')}</p>
          <div className="flex gap-2">
            <Chip active={lang === 'da'} onClick={() => setLocale('da')}>Dansk</Chip>
            <Chip active={lang === 'en'} onClick={() => setLocale('en')}>English</Chip>
          </div>
        </Card>
        <Card>
          <h2 className="mb-1 text-lg font-bold">{t('settings.account')}</h2>
          <p className="mb-3 text-sm text-ink-500">
            {me?.user?.display_name ?? 'Kiosk'} ({me?.user?.username ?? 'kiosk'}) · {me?.household.name}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void logout()}>
              <LogOut className="size-4" /> {t('settings.logout')}
            </Button>
            {isAdmin && (
              <Link to="/admin" className="inline-flex min-h-11 items-center rounded-xl bg-white px-4 text-sm font-semibold ring-1 ring-cream-200">
                {t('nav.admin')}
              </Link>
            )}
          </div>
        </Card>
      </div>
    </>
  )
}
