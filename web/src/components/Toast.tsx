import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'
import { cn } from '../lib/format'

type Tone = 'success' | 'error' | 'info'
interface ToastItem {
  id: number
  message: string
  tone: Tone
  action?: { label: string; onClick: () => void }
}
interface ToastApi {
  push: (message: string, tone?: Tone, action?: ToastItem['action']) => void
}

const Ctx = createContext<ToastApi>({ push: () => {} })
export const useToast = () => useContext(Ctx)

const icons = { success: CheckCircle2, error: AlertCircle, info: Info }
const tones: Record<Tone, string> = {
  success: 'text-leaf-600',
  error: 'text-tomato-600',
  info: 'text-sky-500',
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const seq = useRef(0)
  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), [])
  const push = useCallback<ToastApi['push']>(
    (message, tone = 'info', action) => {
      const id = ++seq.current
      setItems((l) => [...l.slice(-3), { id, message, tone, action }])
      setTimeout(() => dismiss(id), action ? 7000 : 4000)
    },
    [dismiss],
  )
  const api = useMemo(() => ({ push }), [push])
  return (
    <Ctx.Provider value={api}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-24 z-[60] flex flex-col items-center gap-2 px-4 lg:bottom-6"
      >
        {items.map((t) => {
          const Icon = icons[t.tone]
          return (
            <div
              key={t.id}
              className="pn-pop pointer-events-auto flex max-w-md items-center gap-3 rounded-2xl bg-night px-4 py-3 text-sm text-white shadow-lg"
            >
              <Icon className={cn('size-5 shrink-0', tones[t.tone])} aria-hidden />
              <span className="min-w-0 flex-1">{t.message}</span>
              {t.action && (
                <button
                  className="rounded-lg px-2 py-1 font-semibold text-honey-400 hover:bg-white/10"
                  onClick={() => {
                    t.action!.onClick()
                    dismiss(t.id)
                  }}
                >
                  {t.action.label}
                </button>
              )}
              <button aria-label="Luk" className="rounded-lg p-1 hover:bg-white/10" onClick={() => dismiss(t.id)}>
                <X className="size-4" />
              </button>
            </div>
          )
        })}
      </div>
    </Ctx.Provider>
  )
}
