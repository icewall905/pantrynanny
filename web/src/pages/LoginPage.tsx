import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Download, Leaf } from 'lucide-react'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { Button, Card, Field, Input, Spinner } from '../components/ui'
import { ANDROID_APK_URL, useAndroidApp } from '../lib/androidApp'

export default function LoginPage() {
  const { t } = useTranslation()
  const { me, loading, login } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const from = (loc.state as { from?: string } | null)?.from ?? '/'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const apk = useAndroidApp()

  if (loading) return <Spinner />
  if (me) return <Navigate to={me.kiosk ? '/scan' : from} replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const m = await login(username.trim(), password, remember)
      nav(m.kiosk ? '/scan' : from, { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) setError(t('login.tooMany'))
      else if (err instanceof ApiError && (err.status === 401 || err.status === 422)) setError(t('login.invalid'))
      else setError(t('login.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-dvh place-items-center bg-gradient-to-b from-leaf-50 to-cream-100 p-4">
      <Card className="w-full max-w-sm p-6 sm:p-8">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <div className="grid size-16 place-items-center rounded-3xl bg-leaf-600 text-white shadow-md">
            <Leaf className="size-8" />
          </div>
          <h1 className="text-2xl font-extrabold">PantryNanny</h1>
          <p className="text-sm text-ink-500">{t('login.subtitle')}</p>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <Field label={t('login.username')}>
            {(id) => (
              <Input id={id} autoComplete="username" autoCapitalize="none" required value={username} onChange={(e) => setUsername(e.target.value)} />
            )}
          </Field>
          <Field label={t('login.password')}>
            {(id) => (
              <Input id={id} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            )}
          </Field>
          <label className="flex min-h-11 items-center gap-3 text-sm">
            <input type="checkbox" className="size-5 accent-leaf-600" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            {t('login.remember')}
          </label>
          {error && (
            <p role="alert" className="rounded-xl bg-tomato-50 p-3 text-sm text-tomato-600">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>
            {t('login.submit')}
          </Button>
        </form>
        {apk.data && (
          <a href={ANDROID_APK_URL} download="pantrynanny.apk" className="mt-5 flex items-center justify-center gap-2 text-sm font-semibold text-leaf-700">
            <Download className="size-4" /> {t('login.androidApp')}
          </a>
        )}
      </Card>
    </div>
  )
}
