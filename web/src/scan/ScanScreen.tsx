import clsx from 'clsx'
import { AlertTriangle, Flashlight, Keyboard, MapPin, Minus, Plus, RefreshCw, Undo2, Volume2, VolumeX, Wifi, WifiOff, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useTranslation } from 'react-i18next'
import { get, qs } from '../api/client'
import type { BarcodeLookupResult, HouseholdSettings, Location, Product } from '../api/types'
import { enqueueOp, getStore, isBlankBarcode, normalizeBarcode, useSyncStatus } from '../offline'
import type { FailedRecord } from '../offline'
import { CameraError } from './camera'
import { DEFAULT_REARM_MS } from './dedupe'
import { ScannerEngine, type EngineState, type ScanEvent } from './engine'
import { beep, setSoundEnabled, vibrate } from './feedback'
import { FRAME } from './geometry'
import { NS } from './i18n'
import { opErrorText } from '../lib/opError'
import { loadMode, removeTimedOut, saveMode, type ScanMode } from './mode'
import { perf } from './perf'
import type { WakeState } from './wakelock'

// Whole-screen treatment per mode. Full class strings so Tailwind can see them.
const THEME = {
  add: {
    root: 'bg-[#0b2a18]',
    band: 'bg-leaf-600',
    ring: 'border-leaf-500',
    glow: 'shadow-[0_0_60px_8px_rgba(47,154,92,0.55)]',
    active: 'bg-white text-leaf-700',
    chip: 'bg-leaf-500 text-white',
    soft: 'bg-leaf-700/40',
    accent: 'text-leaf-100',
    flash: 'bg-leaf-100/60',
  },
  remove: {
    root: 'bg-[#33120a]',
    band: 'bg-tomato-600',
    ring: 'border-tomato-500',
    glow: 'shadow-[0_0_60px_8px_rgba(232,97,58,0.6)]',
    active: 'bg-white text-tomato-600',
    chip: 'bg-tomato-500 text-white',
    soft: 'bg-tomato-600/40',
    accent: 'text-tomato-100',
    flash: 'bg-tomato-100/60',
  },
} as const

interface Card {
  n: number
  opId: string
  type: ScanMode
  barcode: string
  product: Product | null
  qty: number | null
  lookingUp: boolean
  /** the durable local write failed: this scan was NOT recorded */
  failed?: boolean
}

interface Toast {
  id: number
  text: string
  tone: 'amber' | 'info' | 'red'
}

type HistoryRow = Awaited<ReturnType<ReturnType<typeof getStore>['getHistory']>>[number]

export interface ScanScreenProps {
  settings: HouseholdSettings | null
  kiosk: boolean
  wake: WakeState
  onExit?: () => void
  /** sync lost its session (401): let the user pair/log in again */
  onReauth?: () => void
}

export default function ScanScreen({ settings, kiosk, wake, onExit, onReauth }: ScanScreenProps) {
  const { t, i18n } = useTranslation(NS)
  const store = getStore()
  const sync = useSyncStatus()

  const [mode, setModeState] = useState<ScanMode>(() => loadMode())
  const modeRef = useRef(mode)
  const lastActivity = useRef(Date.now())
  const [card, setCard] = useState<Card | null>(null)
  const cardRef = useRef<Card | null>(null)
  cardRef.current = card
  const [history, setHistory] = useState<HistoryRow[]>([])
  const [toasts, setToasts] = useState<Toast[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [locationId, setLocationId] = useState<string | null>(() => {
    try {
      return localStorage.getItem('pn.scan.location')
    } catch {
      return null
    }
  })
  const locationRef = useRef(locationId)
  locationRef.current = locationId
  const [locOpen, setLocOpen] = useState(false)
  const [sound, setSound] = useState(() => {
    try {
      return localStorage.getItem('pn.scan.sound') !== '0'
    } catch {
      return true
    }
  })
  const [torch, setTorch] = useState(false)
  const [torchOk, setTorchOk] = useState(false)
  const [camState, setCamState] = useState<EngineState>('idle')
  const [camErr, setCamErr] = useState<CameraError | null>(null)
  const [manualOpen, setManualOpen] = useState(false)
  const [manual, setManual] = useState('')
  const [debug, setDebug] = useState(false)
  const [failed, setFailed] = useState<FailedRecord[]>([])
  const [failedOpen, setFailedOpen] = useState(false)
  const pillTaps = useRef<number[]>([])

  const videoRef = useRef<HTMLVideoElement>(null)
  const engineRef = useRef<ScannerEngine | null>(null)
  const chain = useRef<Promise<void>>(Promise.resolve())
  const toastId = useRef(0)
  const cardN = useRef(0)

  const theme = THEME[mode]

  const toast = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    const id = ++toastId.current
    setToasts((l) => [...l.slice(-2), { id, text, tone }])
    // errors stay until tapped: a lost scan must not go unnoticed
    if (tone !== 'red') setTimeout(() => setToasts((l) => l.filter((x) => x.id !== id)), 5000)
    return id
  }, [])
  const dropToast = (id: number) => setToasts((l) => l.filter((x) => x.id !== id))

  // ---- mode ----
  const setMode = useCallback((m: ScanMode) => {
    modeRef.current = m
    lastActivity.current = Date.now()
    engineRef.current?.dedupe.clear() // contract §4: mode switch clears tracked codes
    saveMode(m)
    setModeState(m)
    vibrate(20)
  }, [])

  useEffect(() => {
    const iv = setInterval(() => {
      const min = settings?.remove_mode_timeout_min ?? 10
      if (removeTimedOut(modeRef.current, lastActivity.current, Date.now(), min)) {
        setMode('add')
        toast(t('mode.revertedIdle'))
      }
    }, 5000)
    return () => clearInterval(iv)
  }, [settings?.remove_mode_timeout_min, setMode, toast, t])

  // ---- data refresh ----
  const refresh = useCallback(async () => {
    setHistory(await store.getHistory(20))
    setFailed(await store.getFailedOps())
    setLocations(await store.getLocations())
    const c = cardRef.current
    if (c) {
      const norm = normalizeBarcode(c.barcode)
      const p = c.product ?? (await store.lookupBarcode(c.barcode)).product
      const q = await store.displayedQuantity(p, norm)
      setCard((cur) => (cur && cur.n === c.n ? { ...cur, product: cur.product ?? p, qty: Math.max(0, q) } : cur))
    }
  }, [store])
  useEffect(() => {
    void refresh()
    const off = store.subscribeData(() => void refresh())
    return () => void off()
  }, [store, refresh])

  // ---- scanning ----
  const background = useCallback(
    async (ev: { value: string; format: string }, n: number, toastIdUnknown: number) => {
      try {
        const r = await get<BarcodeLookupResult>(
          `/products/by-barcode/${encodeURIComponent(ev.value)}${qs({ lookup: true, symbology: ev.format })}`,
          { timeoutMs: 6000 },
        )
        if (r.product) {
          await store.cacheProduct(r.product)
          if (r.product.status === 'known') dropToast(toastIdUnknown)
          const q = await store.displayedQuantity(r.product, normalizeBarcode(ev.value, ev.format))
          setCard((c) => (c && c.n === n ? { ...c, product: r.product, lookingUp: false, qty: Math.max(0, q) } : c))
          return
        }
      } catch {
        /* offline or slow: card stays "unknown", op is queued anyway */
      }
      setCard((c) => (c && c.n === n ? { ...c, lookingUp: false } : c))
    },
    [store],
  )

  const handleScan = useCallback(
    async (ev: ScanEvent | { value: string; format: string; frameAt?: number }) => {
      if (isBlankBarcode(ev.value)) {
        beep('error')
        toast(t('toast.invalidBarcode'), 'red')
        return
      }
      // safety: REMOVE that sat idle too long must not apply to this scan
      if (removeTimedOut(modeRef.current, lastActivity.current, Date.now(), settings?.remove_mode_timeout_min ?? 10)) {
        setMode('add')
        toast(t('mode.revertedIdle'))
      }
      const type = modeRef.current
      lastActivity.current = Date.now()
      const n = ++cardN.current
      let product: Product | null = null
      let norm = normalizeBarcode(ev.value, ev.format)
      let op: Awaited<ReturnType<typeof enqueueOp>>
      try {
        const look = await store.lookupBarcode(ev.value, ev.format)
        product = look.product
        norm = look.norm
        op = await enqueueOp({
          type,
          barcode: ev.value,
          symbology: ev.format,
          product_id: product?.id ?? null,
          quantity: 1,
          location_id: locationRef.current,
        })
      } catch (e) {
        // The scan was NOT durably stored: never show success.
        console.error('enqueue failed', e)
        beep('error')
        vibrate([200, 80, 200])
        setCard({ n, opId: '', type, barcode: ev.value, product, qty: null, lookingUp: false, failed: true })
        toast(t('toast.saveFailed', { code: ev.value }), 'red')
        return
      }
      // Success feedback only after the durable local write (a few ms).
      const known = !!product && product.status !== 'unknown'
      beep(known ? type : 'unknown')
      vibrate(known ? 40 : [40, 60, 40])
      setCard({ n, opId: op.client_op_id, type, barcode: ev.value, product, qty: null, lookingUp: !known })
      let unknownToast = 0
      if (!known) unknownToast = toast(t('toast.unknown'), 'amber')
      const q = await store.displayedQuantity(product, norm).catch(() => 0)
      setCard((c) => (c && c.n === n ? { ...c, qty: Math.max(0, q) } : c))
      if ('frameAt' in ev && ev.frameAt !== undefined) {
        const at = ev.frameAt
        requestAnimationFrame(() => perf.latency(performance.now() - at))
      }
      if (!known) void background(ev, n, unknownToast)
    },
    [store, toast, t, background, setMode, settings?.remove_mode_timeout_min],
  )
  const handleScanRef = useRef(handleScan)
  handleScanRef.current = handleScan

  const submit = useCallback((ev: ScanEvent | { value: string; format: string }) => {
    // Serialise so ops get monotonically increasing seq in scan order.
    chain.current = chain.current.then(() => handleScanRef.current(ev)).catch(() => undefined)
  }, [])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const engine = new ScannerEngine({
      video,
      rearmMs: settings?.scan_rearm_ms ?? DEFAULT_REARM_MS,
      onScan: submit,
      onState: (s, err) => {
        setCamState(s)
        setCamErr(err ?? null)
        if (s === 'running') setTorchOk(engine.torchSupported)
      },
    })
    engineRef.current = engine
    void engine.start()
    return () => {
      engine.stop()
      engineRef.current = null
    }
    // engine is created once per mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    engineRef.current?.dedupe.setRearmMs(settings?.scan_rearm_ms ?? DEFAULT_REARM_MS)
  }, [settings?.scan_rearm_ms])
  useEffect(() => setSoundEnabled(sound), [sound])

  // ---- actions ----
  const undoRow = async (id: string, name?: string) => {
    lastActivity.current = Date.now()
    const r = await store.undoScan(id)
    if (r !== 'noop') {
      beep('remove')
      toast(t('toast.undone', { name: name ?? '' }))
    }
    await refresh()
  }
  const lastUndoable = history.find((h) => !h.undone)
  const undoLast = () => (lastUndoable ? undoRow(lastUndoable.client_op_id, lastUndoable.product?.name ?? lastUndoable.barcode) : toast(t('toast.undoNothing')))

  const pickLocation = (id: string | null) => {
    setLocationId(id)
    setLocOpen(false)
    try {
      if (id) localStorage.setItem('pn.scan.location', id)
      else localStorage.removeItem('pn.scan.location')
    } catch {
      /* ignore */
    }
  }
  const locName = locations.find((l) => l.id === locationId)?.name ?? t('location.auto')

  const pillTap = () => {
    const now = Date.now()
    pillTaps.current = [...pillTaps.current.filter((x) => now - x < 3000), now]
    if (pillTaps.current.length >= 5) {
      pillTaps.current = []
      setDebug((d) => !d)
    }
  }

  const camTitleKey = camErr ? `camera.${camErr.kind}` : null

  return (
    <div
      className={clsx('fixed inset-0 z-50 flex select-none flex-col overflow-hidden text-white transition-colors duration-200', theme.root)}
      style={{ paddingTop: 'env(safe-area-inset-top)', paddingBottom: 'env(safe-area-inset-bottom)' }}
      data-testid="scan-screen"
      data-mode={mode}
    >
      <style>{`
        @keyframes pn-pop{0%{transform:scale(.4);opacity:0}35%{transform:scale(1.3);opacity:1}100%{transform:scale(1);opacity:1}}
        @keyframes pn-flash{0%{opacity:1}100%{opacity:0}}
        @keyframes pn-slide{0%{transform:translateY(-12px);opacity:0}100%{transform:none;opacity:1}}
        @media (prefers-reduced-motion: reduce){.pn-anim{animation:none!important}}
      `}</style>

      {/* Mode header: huge label + giant segmented control */}
      <header className={clsx('flex shrink-0 flex-col gap-3 px-4 pb-3 pt-3 landscape:flex-row landscape:items-center landscape:gap-6', theme.band)}>
        <div className="min-w-0 flex-1" aria-live="polite">
          <div className="text-[clamp(1.6rem,4.4vw,4rem)] font-black leading-[0.95] tracking-tight portrait:text-[clamp(1.75rem,8vw,4rem)]" data-testid="mode-label">
            {mode === 'add' ? t('mode.adding') : t('mode.removing')}
          </div>
        </div>
        <div
          role="group"
          aria-label={t('mode.label')}
          className="grid min-w-0 grid-cols-2 gap-2 rounded-3xl bg-black/25 p-2 landscape:w-[min(44vw,36rem)]"
        >
          {(['add', 'remove'] as const).map((m) => (
            <button
              key={m}
              type="button"
              data-testid={`mode-${m}`}
              aria-pressed={mode === m}
              onClick={() => mode !== m && setMode(m)}
              className={clsx(
                'flex min-h-[4.5rem] items-center justify-center gap-3 rounded-2xl text-[clamp(1.5rem,5vw,3rem)] font-black transition-all active:scale-95 landscape:min-h-[5rem]',
                mode === m ? clsx(THEME[m].active, 'shadow-xl') : 'text-white/70',
              )}
            >
              {m === 'add' ? <Plus className="size-[1.1em]" strokeWidth={4} /> : <Minus className="size-[1.1em]" strokeWidth={4} />}
              {t(`mode.${m}`)}
            </button>
          ))}
        </div>
      </header>

      <div className="relative flex min-h-0 flex-1 flex-col gap-3 p-3 landscape:flex-row">
        {/* Camera */}
        <div
          className={clsx('relative min-h-[30vh] flex-1 overflow-hidden rounded-3xl border-[10px] bg-black landscape:flex-[3]', theme.ring, theme.glow)}
        >
          <video ref={videoRef} playsInline muted autoPlay className="absolute inset-0 size-full object-cover" data-testid="scan-video" />
          {/* aiming frame (decoder looks only inside it) */}
          <div
            className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-2xl border-2 border-white/70"
            style={{ width: `${FRAME.w * 100}%`, height: `${FRAME.h * 100}%`, boxShadow: '0 0 0 9999px rgba(0,0,0,0.22)' }}
          />
          {card && <div key={`f${card.n}`} className={clsx('pn-anim pointer-events-none absolute inset-0', theme.flash)} style={{ animation: 'pn-flash .5s ease-out forwards' }} />}
          {camState !== 'running' && !camErr && (
            <div className="absolute inset-0 grid place-items-center bg-black/60 text-xl font-semibold">{t('camera.starting')}</div>
          )}
          {camErr && camTitleKey && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 overflow-auto bg-black/85 p-6 text-center">
              <AlertTriangle className="size-12 text-honey-400" />
              <h2 className="text-2xl font-bold">{t(`${camTitleKey}.title`)}</h2>
              <p className="max-w-xl text-lg text-white/85">{t(`${camTitleKey}.body`)}</p>
              <button
                type="button"
                onClick={() => void engineRef.current?.start()}
                className="mt-2 flex items-center gap-2 rounded-2xl bg-white px-6 py-4 text-xl font-bold text-ink-900"
              >
                <RefreshCw className="size-5" /> {t('camera.retry')}
              </button>
            </div>
          )}
          {/* tools */}
          <div className="absolute bottom-3 right-3 flex gap-2">
            {torchOk && (
              <IconBtn
                label={t('torch')}
                active={torch}
                onClick={async () => {
                  const next = !torch
                  if (await engineRef.current?.setTorch(next)) setTorch(next)
                }}
              >
                <Flashlight className="size-6" />
              </IconBtn>
            )}
            <IconBtn
              label={sound ? t('sound.on') : t('sound.off')}
              onClick={() => {
                const v = !sound
                setSound(v)
                try {
                  localStorage.setItem('pn.scan.sound', v ? '1' : '0')
                } catch {
                  /* ignore */
                }
              }}
            >
              {sound ? <Volume2 className="size-6" /> : <VolumeX className="size-6" />}
            </IconBtn>
            <IconBtn label={t('manual.open')} onClick={() => setManualOpen((o) => !o)}>
              <Keyboard className="size-6" />
            </IconBtn>
          </div>
          {(wake === 'unsupported' || wake === 'failed') && (
            <div className="absolute inset-x-3 bottom-3 mr-44 rounded-xl bg-black/60 px-3 py-2 text-sm">{t(`wake.${wake}`)}</div>
          )}
        </div>

        {/* Side panel */}
        <div className="flex min-h-0 flex-col gap-3 landscape:flex-[2]">
          <LastCard card={card} theme={theme} />
          <div className="flex gap-3">
            <button
              type="button"
              data-testid="undo-last"
              onClick={() => void undoLast()}
              disabled={!lastUndoable}
              className="flex min-h-16 flex-1 items-center justify-center gap-3 rounded-2xl bg-white/15 px-4 text-2xl font-bold ring-2 ring-white/40 active:scale-95 disabled:opacity-40"
            >
              <Undo2 className="size-7" /> {t('undo')}
            </button>
            <div className="relative">
              <button
                type="button"
                onClick={() => setLocOpen((o) => !o)}
                className="flex min-h-16 items-center gap-2 rounded-2xl bg-white/10 px-4 text-lg font-semibold"
              >
                <MapPin className="size-5" />
                {t(mode === 'add' ? 'location.to' : 'location.from', { name: locName })}
              </button>
              {locOpen && (
                <div className="absolute bottom-full right-0 z-20 mb-2 flex max-h-72 w-60 flex-col overflow-auto rounded-2xl bg-ink-900 p-2 shadow-2xl ring-1 ring-white/20">
                  <LocItem active={!locationId} onClick={() => pickLocation(null)}>
                    {t('location.auto')}
                  </LocItem>
                  {locations.map((l) => (
                    <LocItem key={l.id} active={locationId === l.id} onClick={() => pickLocation(l.id)}>
                      {l.name}
                    </LocItem>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className={clsx('min-h-0 flex-1 overflow-auto rounded-2xl p-3', theme.soft)}>
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-white/70">{t('history.title')}</h3>
            {history.length === 0 && <p className="text-white/60">{t('history.empty')}</p>}
            <ul className="flex flex-col gap-1.5">
              {history.map((h) => (
                <li key={h.client_op_id} className={clsx('flex items-center gap-3 rounded-xl bg-black/20 px-3 py-2', h.undone && 'opacity-50')}>
                  <span className={clsx('grid size-9 shrink-0 place-items-center rounded-full text-lg font-black', h.type === 'add' ? 'bg-leaf-500' : 'bg-tomato-500')}>
                    {h.type === 'add' ? '+' : '−'}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={clsx('block truncate text-lg font-semibold', h.undone && 'line-through')}>
                      {h.product && h.product.status !== 'unknown' ? h.product.name : `${t('last.unknown')} ${h.barcode}`}
                    </span>
                    <span className="block text-xs text-white/60">
                      {new Date(h.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                      {h.pending && ` · ${t('last.pending')}`}
                      {h.undone && ` · ${t('history.undone')}`}
                    </span>
                  </span>
                  {!h.undone && (
                    <button
                      type="button"
                      aria-label={t('history.undoRow')}
                      onClick={() => void undoRow(h.client_op_id, h.product?.name ?? h.barcode)}
                      className="grid size-11 shrink-0 place-items-center rounded-xl bg-white/15 active:scale-90"
                    >
                      <Undo2 className="size-5" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Toasts */}
        <div className="pointer-events-none absolute inset-x-0 bottom-6 z-30 flex flex-col items-center gap-2 px-4">
          {toasts.map((x) => (
            <div
              key={x.id}
              role={x.tone === 'red' ? 'alert' : 'status'}
              onClick={x.tone === 'red' ? () => dropToast(x.id) : undefined}
              className={clsx(
                'pn-anim max-w-xl rounded-2xl px-5 py-3 text-lg font-bold shadow-2xl',
                x.tone === 'amber' && 'bg-honey-400 text-ink-900',
                x.tone === 'info' && 'bg-ink-900/95 text-white',
                x.tone === 'red' && 'pointer-events-auto bg-red-600 text-white',
              )}
              style={{ animation: 'pn-slide .2s ease-out' }}
            >
              {x.text}
            </div>
          ))}
        </div>
      </div>

      {/* Footer: status pill, failed banner */}
      <footer className="flex shrink-0 items-center gap-3 px-3 pb-3">
        <button
          type="button"
          data-testid="sync-pill"
          onClick={() => (sync.error === 'unauthorized' && onReauth ? onReauth() : pillTap())}
          className={clsx(
            'flex items-center gap-2 rounded-full px-4 py-2 text-base font-semibold',
            sync.online ? 'bg-white/15' : 'bg-honey-400 text-ink-900',
          )}
        >
          {sync.syncing ? <RefreshCw className="size-4 animate-spin" /> : sync.online ? <Wifi className="size-4" /> : <WifiOff className="size-4" />}
          {sync.syncing
            ? t('status.syncing')
            : sync.error === 'unauthorized'
              ? t('status.unauthorized')
              : !sync.online
              ? sync.pending > 0
                ? t('status.offlinePending', { count: sync.pending })
                : t('status.offline')
              : sync.error
                ? t('status.error')
                : sync.pending > 0
                  ? t('status.pending', { count: sync.pending })
                  : `${t('status.online')} ✓`}
        </button>
        {sync.failed > 0 && (
          <button
            type="button"
            onClick={() => setFailedOpen(true)}
            className="flex items-center gap-2 rounded-full bg-red-600 px-4 py-2 text-base font-bold"
          >
            <AlertTriangle className="size-4" /> {t('failed.banner', { count: sync.failed })}
          </button>
        )}
        <div className="flex-1" />
        {!kiosk && onExit && (
          <button type="button" onClick={onExit} className="rounded-full bg-white/10 px-4 py-2 text-sm">
            {t('exit')}
          </button>
        )}
      </footer>

      {manualOpen && (
        <form
          className="absolute inset-x-0 bottom-0 z-40 flex gap-3 bg-ink-900 p-4 shadow-2xl"
          onSubmit={(e) => {
            e.preventDefault()
            const v = manual
            if (!v) return
            if (isBlankBarcode(v)) {
              toast(t('toast.invalidBarcode'), 'red')
              return
            }
            setManual('')
            setManualOpen(false)
            submit({ value: v, format: 'other' })
          }}
        >
          <input
            autoFocus
            inputMode="numeric"
            value={manual}
            onChange={(e) => setManual(e.target.value)}
            placeholder={t('manual.placeholder')}
            className="min-w-0 flex-1 rounded-2xl bg-white px-4 py-4 text-2xl text-ink-900"
          />
          <button type="submit" className={clsx('rounded-2xl px-6 text-xl font-bold', theme.chip)}>
            {t('manual.submit')}
          </button>
          <button type="button" aria-label="close" onClick={() => setManualOpen(false)} className="grid size-14 place-items-center rounded-2xl bg-white/15">
            <X />
          </button>
        </form>
      )}

      {failedOpen && (
        <div className="absolute inset-0 z-50 grid place-items-center bg-black/70 p-4">
          <div className="max-h-full w-full max-w-2xl overflow-auto rounded-3xl bg-ink-900 p-5">
            <h2 className="mb-3 text-2xl font-bold">{t('failed.title')}</h2>
            <ul className="flex flex-col gap-2">
              {failed.map((f) => (
                <li key={f.client_op_id} className="rounded-xl bg-white/10 p-3">
                  <div className="font-semibold">
                    {f.op.type} × {f.op.quantity} · {f.op.barcode ?? f.op.product_id}
                  </div>
                  <div className="text-sm text-red-300">{opErrorText(i18n, f.error_code, f.error)}</div>
                  <div className="mt-2 flex gap-2">
                    <button type="button" className="rounded-lg bg-white/15 px-3 py-2" onClick={() => void store.retryFailedOp(f.client_op_id)}>
                      {t('failed.retry')}
                    </button>
                    <button type="button" className="rounded-lg bg-white/15 px-3 py-2" onClick={() => void store.dismissFailedOp(f.client_op_id)}>
                      {t('failed.dismiss')}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            <button type="button" onClick={() => setFailedOpen(false)} className="mt-4 w-full rounded-2xl bg-white py-3 text-lg font-bold text-ink-900">
              {t('failed.close')}
            </button>
          </div>
        </div>
      )}

      {debug && <DebugOverlay pending={sync.pending} onClose={() => setDebug(false)} />}
    </div>
  )
}

function IconBtn({ children, label, onClick, active }: { children: React.ReactNode; label: string; onClick: () => void; active?: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={clsx('grid size-14 place-items-center rounded-2xl backdrop-blur active:scale-90', active ? 'bg-honey-400 text-ink-900' : 'bg-black/55 text-white')}
    >
      {children}
    </button>
  )
}

function LocItem({ children, active, onClick }: { children: React.ReactNode; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={clsx('rounded-xl px-4 py-3 text-left text-lg', active ? 'bg-white text-ink-900 font-bold' : 'text-white')}>
      {children}
    </button>
  )
}

function LastCard({ card, theme }: { card: Card | null; theme: (typeof THEME)[ScanMode] }) {
  const { t } = useTranslation(NS)
  if (!card)
    return (
      <div className={clsx('grid min-h-28 place-items-center rounded-3xl p-5 text-center text-xl text-white/80', theme.soft)}>{t('last.empty')}</div>
    )
  const p = card.product && card.product.status !== 'unknown' ? card.product : null
  const delta = card.failed ? '!' : card.type === 'add' ? '+1' : '−1'
  return (
    <div key={card.n} className={clsx('flex items-center gap-4 rounded-3xl p-4', theme.soft)} data-testid="last-card">
      <div className="relative grid size-24 shrink-0 place-items-center overflow-hidden rounded-2xl bg-white/90 text-5xl landscape:size-28">
        {p?.image_url ? <img src={p.image_url} alt="" className="size-full object-contain" /> : <span aria-hidden>{p ? '🛒' : '❓'}</span>}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[clamp(1.5rem,3.2vw,2.5rem)] font-black leading-tight" data-testid="last-name">
          {p ? p.name : t('last.unknown')}
        </div>
        {p?.brand && <div className="truncate text-lg text-white/70">{p.brand}</div>}
        {!p && <div className="truncate font-mono text-lg text-white/80">{card.barcode}</div>}
        {card.failed && <div className="mt-1 text-lg font-bold text-red-300">{t('toast.notSaved')}</div>}
        <div className="mt-1 text-lg text-white/80">
          {card.lookingUp ? t('last.lookingUp') : card.qty !== null ? `${t('last.stock')}: ${card.qty}` : ''}
        </div>
      </div>
      <div
        className={clsx('pn-anim text-[clamp(3rem,8vw,6rem)] font-black leading-none', card.failed ? 'text-red-400' : card.type === 'add' ? 'text-leaf-100' : 'text-tomato-100')}
        style={{ animation: 'pn-pop .45s ease-out' }}
        aria-label={delta}
      >
        {delta}
      </div>
    </div>
  )
}

function DebugOverlay({ pending, onClose }: { pending: number; onClose: () => void }) {
  const p = useSyncExternalStore(perf.subscribe, perf.get, perf.get)
  return (
    <button type="button" onClick={onClose} className="absolute left-3 top-24 z-50 rounded-xl bg-black/85 p-3 text-left font-mono text-xs leading-5 text-lime-300" data-testid="debug-overlay">
      <div>decoder: {p.decoder}</div>
      <div>fps: {p.fps}</div>
      <div>decode: {p.decodeMs.toFixed(1)} ms</div>
      <div>decode→UI: {p.latencyMs === null ? '-' : `${p.latencyMs.toFixed(0)} ms`}</div>
      <div>last: {p.lastLatencies.map((x) => x.toFixed(0)).join(', ')}</div>
      <div>pending ops: {pending}</div>
      <div>frames: {p.frames}</div>
    </button>
  )
}
