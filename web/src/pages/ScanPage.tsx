// /scan – full-screen continuous scanning station (wall-mounted iPad, phones, tablets).
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { HouseholdSettings, Me } from '../api/types'
import { getStore, registerServiceWorker, startSync } from '../offline'
import { checkSession, loginRemember, logout, pairKiosk, type AuthError } from '../scan/auth'
import { armAudioUnlock, unlockAudio } from '../scan/feedback'
import { parseScanParams, stripModeParam, swapToScanManifest } from '../scan/link'
import { canAutostartCamera, loadScanPrefs, saveScanPrefs } from '../scan/prefs'
import { NS } from '../scan/i18n'
import type { ScanMode } from '../scan/mode'
import ScanScreen from '../scan/ScanScreen'
import { WakeLock, type WakeState } from '../scan/wakelock'

const RESUME_KEY = 'pn.scan.resume'

/** Best effort: was scanning active before the reload and is the camera permission still granted? */
async function canAutoResume(): Promise<boolean> {
  try {
    if (localStorage.getItem(RESUME_KEY) !== '1') return false
    const st = await navigator.permissions?.query({ name: 'camera' as PermissionName })
    return st?.state === 'granted'
  } catch {
    return false // e.g. Safari without camera permission query: a tap is required
  }
}

type Phase = 'checking' | 'unauth' | 'ready' | 'scanning'

export default function ScanPage() {
  const { t } = useTranslation(NS)
  const [phase, setPhase] = useState<Phase>('checking')
  const [me, setMe] = useState<Me | null>(null)
  const [settings, setSettings] = useState<HouseholdSettings | null>(null)
  const [wake, setWake] = useState<WakeState>('idle')
  const wakeRef = useRef<WakeLock | null>(null)
  const [dropped, setDropped] = useState(0)
  // direct scanner link: /scan?autostart=1&mode=remove&camera=off (read once per visit)
  const [params] = useState(() => parseScanParams(window.location.search))

  const [linkMode, setLinkMode] = useState<ScanMode | undefined>(params.mode === 'remove' ? 'remove' : undefined) // one-shot

  // "Add to Home Screen" from this page must install the scanner, not the whole app.
  useEffect(() => swapToScanManifest(), [])

  useEffect(() => {
    void registerServiceWorker()
    stripModeParam() // one-shot: a reload must not re-apply REMOVE
    if (params.camera) saveScanPrefs({ ...loadScanPrefs(), camera: params.camera === 'on' })
    let alive = true
    void (async () => {
      const r = await checkSession()
      if (!alive) return
      if (r.kind === 'ok') {
        setMe(r.me)
        setSettings(r.me.settings)
        startSync()
        if (r.droppedPending) setDropped(r.droppedPending)
        // After a reload (e.g. service-worker update) or via the direct link continue without a tap when possible.
        if ((await canAutoResume()) || (params.autostart && (await canAutostartCamera(loadScanPrefs())))) {
          armAudioUnlock() // audio itself waits for the next touch
          wakeRef.current ??= new WakeLock(setWake)
          void wakeRef.current.acquire()
          const retry = () => void wakeRef.current?.acquire()
          document.addEventListener('pointerdown', retry, { once: true, passive: true })
          if (alive) setPhase('scanning')
        } else setPhase('ready')
      } else setPhase('unauth')
    })()
    return () => {
      alive = false
      void wakeRef.current?.release()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const authed = (m: Me) => {
    setMe(m)
    setSettings(m.settings)
    startSync()
    // pairing/login was a user gesture: a direct scanner link carries straight on into scanning
    if (params.autostart) void start()
    else setPhase('ready')
  }

  const start = async () => {
    // Everything that needs a user gesture happens here.
    unlockAudio()
    wakeRef.current ??= new WakeLock(setWake)
    void wakeRef.current.acquire()
    try {
      localStorage.setItem(RESUME_KEY, '1')
    } catch {
      /* ignore */
    }
    setPhase('scanning')
  }

  const shell = 'fixed inset-0 z-50 grid place-items-center overflow-auto bg-leaf-700 p-6 text-white'

  if (phase === 'checking') return <div className={shell} />
  if (phase === 'unauth') return <PairScreen onDone={authed} />
  if (phase === 'scanning')
    return (
      <ScanScreen
        settings={settings}
        kiosk={me?.kiosk ?? false}
        wake={wake}
        initialMode={linkMode}
        onReauth={() => setPhase('unauth')}
        onExit={() => {
          setLinkMode(undefined)
          try {
            localStorage.removeItem(RESUME_KEY)
          } catch {
            /* ignore */
          }
          void wakeRef.current?.release()
          setPhase('ready')
        }}
      />
    )

  return (
    <div className={shell}>
      <div className="flex w-full max-w-xl flex-col items-center gap-6 text-center">
        <img src="/favicon.svg" alt="" className="size-20" />
        <h1 className="text-4xl font-black">{t('start.title')}</h1>
        <button
          type="button"
          data-testid="start-scanning"
          onClick={() => void start()}
          className="w-full rounded-3xl bg-white px-8 py-10 text-4xl font-black text-leaf-700 shadow-2xl active:scale-95"
        >
          {t('start.button')}
        </button>
        <p className="text-lg text-white/85">{t('start.hint')}</p>
        {dropped > 0 && <p className="rounded-xl bg-honey-400 px-4 py-3 text-ink-900">{t('start.dropped', { count: dropped })}</p>}
        {typeof navigator !== 'undefined' && !navigator.onLine && <p className="text-base text-honey-400">{t('start.offlineReady')}</p>}
        {!me?.kiosk && (
          <button
            type="button"
            className="text-sm underline opacity-80"
            onClick={async () => {
              try {
                localStorage.removeItem(RESUME_KEY)
              } catch {
                /* ignore */
              }
              await logout()
              setPhase('unauth')
            }}
          >
            {t('start.logout')}
          </button>
        )}
      </div>
    </div>
  )
}

function PairScreen({ onDone }: { onDone: (me: Me) => void }) {
  const { t } = useTranslation(NS)
  const [code, setCode] = useState('')
  const [user, setUser] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState<AuthError | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async (p: Promise<{ me: Me } | { error: AuthError }>) => {
    setBusy(true)
    setErr(null)
    const r = await p
    setBusy(false)
    if ('me' in r) {
      // fresh install: make sure the local cache is warm before the first scan
      void getStore().syncNow({ pull: true })
      onDone(r.me)
    } else setErr(r.error)
  }
  const msg = (kind: 'pair' | 'login') =>
    err === 'offline' ? t('pair.offline') : err === 'rate' ? t('pair.tooMany') : err ? t(kind === 'pair' ? 'pair.error' : 'pair.loginError') : null

  const input = 'w-full rounded-2xl bg-white px-4 py-4 text-2xl text-ink-900 placeholder:text-ink-300'
  const btn = 'w-full rounded-2xl bg-white px-6 py-4 text-2xl font-bold text-leaf-700 disabled:opacity-50 active:scale-95'

  return (
    <div className="fixed inset-0 z-50 overflow-auto bg-leaf-700 p-6 text-white" data-testid="pair-screen">
      <div className="mx-auto flex max-w-xl flex-col gap-6 py-8">
        <img src="/favicon.svg" alt="" className="size-16" />
        <h1 className="text-4xl font-black">{t('pair.title')}</h1>
        <p className="text-lg text-white/85">{t('pair.intro')}</p>

        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (code.trim().length >= 8) void run(pairKiosk(code))
          }}
        >
          <label className="text-sm font-semibold uppercase tracking-wide" htmlFor="pn-code">
            {t('pair.codeLabel')}
          </label>
          <input
            id="pn-code"
            data-testid="pair-code"
            className={`${input} text-center font-mono tracking-[0.3em] uppercase`}
            value={code}
            autoCapitalize="characters"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            placeholder={t('pair.codePlaceholder')}
            onChange={(e) => setCode(e.target.value.replace(/[^a-z0-9]/gi, '').toUpperCase().slice(0, 8))}
          />
          <button type="submit" className={btn} disabled={busy || code.length < 8}>
            {t('pair.submit')}
          </button>
          {err && code && <p className="rounded-xl bg-red-700/80 px-4 py-3">{msg('pair')}</p>}
        </form>

        <div className="flex items-center gap-4 text-white/70">
          <hr className="flex-1 border-white/30" /> {t('pair.or')} <hr className="flex-1 border-white/30" />
        </div>

        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (user && pw) void run(loginRemember(user, pw))
          }}
        >
          <h2 className="text-xl font-bold">{t('pair.loginTitle')}</h2>
          <input className={input} value={user} onChange={(e) => setUser(e.target.value)} placeholder={t('pair.username')} autoCapitalize="none" autoComplete="username" />
          <input className={input} type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder={t('pair.password')} autoComplete="current-password" />
          <button type="submit" className={btn} disabled={busy || !user || !pw}>
            {t('pair.login')}
          </button>
          {err && !code && <p className="rounded-xl bg-red-700/80 px-4 py-3">{msg('login')}</p>}
        </form>
      </div>
    </div>
  )
}
