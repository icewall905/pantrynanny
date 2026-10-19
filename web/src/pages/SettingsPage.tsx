import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Download, LogOut, Sparkles } from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'
import { setLocale } from '../i18n'
import { Button, Card, Chip, PageHeader } from '../components/ui'
import { ANDROID_APK_URL, useAndroidApp } from '../lib/androidApp'
import { formatDate } from '../lib/format'
import { getTheme, setTheme, type Theme } from '../lib/theme'
import ScannerSettingsCard from './ScannerSettingsCard'

export default function SettingsPage() {
  const { t, i18n } = useTranslation()
  const { me, logout, isAdmin } = useAuth()
  const lang = i18n.language.startsWith('en') ? 'en' : 'da'
  const [theme, setThemeState] = useState<Theme>(getTheme)
  const pickTheme = (th: Theme) => {
    setTheme(th)
    setThemeState(th)
  }
  const apk = useAndroidApp()
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
          <h2 className="mb-1 text-lg font-bold">{t('settings.theme')}</h2>
          <p className="mb-3 text-sm text-ink-500">{t('settings.themeHint')}</p>
          <div className="flex gap-2">
            <Chip active={theme === 'dark'} onClick={() => pickTheme('dark')}>{t('settings.dark')}</Chip>
            <Chip active={theme === 'light'} onClick={() => pickTheme('light')}>{t('settings.light')}</Chip>
          </div>
        </Card>
        <Card>
          <h2 className="mb-1 text-lg font-bold">{t('settings.android')}</h2>
          <p className="mb-3 text-sm text-ink-500">{t('settings.androidHint')}</p>
          {apk.data ? (
            <>
              <a
                href={ANDROID_APK_URL}
                download="pantrynanny.apk"
                className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-leaf-600 px-4 text-sm font-semibold text-white hover:bg-leaf-800"
              >
                <Download className="size-4" /> {t('settings.androidDownload')}
              </a>
              <p className="mt-2 text-xs text-ink-500">
                {t('settings.androidVersion', {
                  version: apk.data.version_name,
                  date: formatDate(apk.data.built.slice(0, 10), i18n.language),
                  size: (apk.data.size / 1024 / 1024).toFixed(1),
                })}
              </p>
              <p className="mt-1 text-xs text-ink-500">{t('settings.androidInstallHint')}</p>
            </>
          ) : (
            !apk.isLoading && <p className="text-sm text-ink-500">{t('settings.androidNone')}</p>
          )}
        </Card>
        <ScannerSettingsCard />
        {isAdmin && (
          <Card>
            <h2 className="mb-1 flex items-center gap-2 text-lg font-bold">
              <Sparkles className="size-5 text-leaf-600" /> {t('adminAi.settingsCard')}
            </h2>
            <p className="mb-3 text-sm text-ink-500">{t('adminAi.settingsCardHint')}</p>
            <Link
              to="/admin?tab=ai"
              className="inline-flex min-h-11 items-center rounded-xl bg-surface px-4 text-sm font-semibold ring-1 ring-cream-200 hover:bg-cream-200/70"
            >
              {t('adminAi.open')}
            </Link>
          </Card>
        )}
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
              <Link to="/admin" className="inline-flex min-h-11 items-center rounded-xl bg-surface px-4 text-sm font-semibold ring-1 ring-cream-200">
                {t('nav.admin')}
              </Link>
            )}
          </div>
        </Card>
      </div>
    </>
  )
}
