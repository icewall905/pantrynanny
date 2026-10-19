import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'
import { AlertTriangle, Loader2, MoreVertical, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '../lib/format'

/* ---------- Button ---------- */
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
const variants: Record<Variant, string> = {
  primary: 'bg-leaf-600 text-white hover:bg-leaf-700 shadow-sm',
  secondary: 'bg-white text-ink-900 ring-1 ring-cream-200 hover:bg-cream-200',
  ghost: 'text-ink-700 hover:bg-cream-200',
  danger: 'bg-tomato-500 text-white hover:bg-tomato-600 shadow-sm',
}
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-xl font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' && 'min-h-9 px-3 text-sm',
        size === 'md' && 'min-h-11 px-4 text-sm',
        size === 'lg' && 'min-h-14 px-6 text-base',
        variants[variant],
        className,
      )}
      {...rest}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
})

export function IconButton({
  label,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        'inline-flex size-11 items-center justify-center rounded-xl text-ink-700 transition-colors hover:bg-cream-200 disabled:opacity-40',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}

/* ---------- Card / Badge ---------- */
export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('rounded-[var(--radius-card)] bg-white p-4 shadow-card sm:p-5', className)} {...rest}>
      {children}
    </div>
  )
}

type Tone = 'neutral' | 'good' | 'warn' | 'bad' | 'info'
const tones: Record<Tone, string> = {
  neutral: 'bg-cream-200 text-ink-700',
  good: 'bg-leaf-100 text-leaf-700',
  warn: 'bg-honey-50 text-honey-600 ring-1 ring-honey-400/50',
  bad: 'bg-tomato-100 text-tomato-600',
  info: 'bg-sky-500/10 text-sky-500',
}
export function Badge({ tone = 'neutral', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold', tones[tone], className)}>
      {children}
    </span>
  )
}

/* ---------- Form fields ---------- */
const inputCls =
  'min-h-11 w-full rounded-xl border border-ink-300/60 bg-white px-3 text-base text-ink-900 placeholder:text-ink-300 focus:border-leaf-500 disabled:bg-cream-100 sm:text-sm'

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string
  hint?: string
  children: (id: string) => ReactNode
  className?: string
}) {
  const id = useId()
  return (
    <div className={cn('block', className)}>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-ink-700">
        {label}
      </label>
      {children(id)}
      {hint && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
    </div>
  )
}
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...r },
  ref,
) {
  return <input ref={ref} className={cn(inputCls, className)} {...r} />
})
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, ...r },
  ref,
) {
  return <select ref={ref} className={cn(inputCls, 'pr-8', className)} {...r} />
})
export function Textarea({ className, ...r }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(inputCls, 'py-2', className)} {...r} />
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  hint?: string
}) {
  return (
    <label className="flex min-h-11 cursor-pointer items-center justify-between gap-4 py-1">
      <span>
        <span className="block text-sm font-medium text-ink-900">{label}</span>
        {hint && <span className="block text-xs text-ink-500">{hint}</span>}
      </span>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-6 shrink-0 accent-leaf-600"
      />
    </label>
  )
}

/* ---------- Modal ---------- */
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
}) {
  const { t } = useTranslation()
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    ref.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      prev?.focus?.()
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="pn-fade fixed inset-0 z-50 flex items-end justify-center bg-ink-900/40 sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="pn-pop flex max-h-[92dvh] w-full flex-col rounded-t-3xl bg-white shadow-xl outline-none sm:max-w-lg sm:rounded-3xl"
      >
        <div className="flex items-center justify-between gap-2 px-5 pt-4">
          <h2 id={titleId} className="text-lg font-bold">
            {title}
          </h2>
          <IconButton label={t('common.close')} onClick={onClose}>
            <X className="size-5" />
          </IconButton>
        </div>
        <div className="overflow-y-auto px-5 py-3">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-cream-200 px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">{footer}</div>}
      </div>
    </div>
  )
}

/* ---------- Dropdown menu ---------- */
export function Menu({
  label,
  items,
  icon,
}: {
  label: string
  items: { label: string; onClick: () => void; danger?: boolean; icon?: ReactNode }[]
  icon?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDoc = (e: Event) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  return (
    <div className="relative" ref={ref}>
      <IconButton label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {icon ?? <MoreVertical className="size-5" />}
      </IconButton>
      {open && (
        <div role="menu" className="pn-pop absolute right-0 z-30 mt-1 min-w-52 rounded-2xl bg-white p-1.5 shadow-xl ring-1 ring-cream-200">
          {items.map((it) => (
            <button
              key={it.label}
              role="menuitem"
              className={cn(
                'flex min-h-11 w-full items-center gap-2 rounded-xl px-3 text-left text-sm hover:bg-cream-100',
                it.danger && 'text-tomato-600',
              )}
              onClick={() => {
                setOpen(false)
                it.onClick()
              }}
            >
              {it.icon}
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* ---------- States ---------- */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('pn-skeleton rounded-xl', className)} />
}
export function ListSkeleton({ rows = 5 }: { rows?: number }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-3" role="status" aria-label={t('common.loading')}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-20 w-full" />
      ))}
    </div>
  )
}
export function EmptyState({ icon, title, hint, action }: { icon?: ReactNode; title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-14 text-center">
      {icon && <div className="grid size-16 place-items-center rounded-3xl bg-leaf-50 text-leaf-600">{icon}</div>}
      <h2 className="text-lg font-bold">{title}</h2>
      {hint && <p className="max-w-sm text-sm text-ink-500">{hint}</p>}
      {action}
    </div>
  )
}
export function ErrorState({ error, onRetry }: { error?: unknown; onRetry?: () => void }) {
  const { t } = useTranslation()
  const msg = error instanceof Error ? error.message : undefined
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-4 py-14 text-center">
      <div className="grid size-16 place-items-center rounded-3xl bg-tomato-50 text-tomato-500">
        <AlertTriangle className="size-8" />
      </div>
      <h2 className="text-lg font-bold">{t('error.title')}</h2>
      <p className="max-w-sm text-sm text-ink-500">{msg && msg !== 'Failed to fetch' ? msg : t('error.hint')}</p>
      {onRetry && (
        <Button onClick={onRetry} variant="primary">
          {t('common.retry')}
        </Button>
      )}
    </div>
  )
}
export function Spinner() {
  const { t } = useTranslation()
  return (
    <div role="status" className="grid min-h-40 place-items-center text-leaf-600">
      <Loader2 className="size-8 animate-spin" aria-label={t('common.loading')} />
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-ink-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div role="tablist" className="-mx-4 mb-5 flex gap-1 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
      {tabs.map((tb) => (
        <button
          key={tb.id}
          role="tab"
          aria-selected={tb.id === value}
          onClick={() => onChange(tb.id)}
          className={cn(
            'min-h-11 shrink-0 rounded-xl px-4 text-sm font-semibold transition-colors',
            tb.id === value ? 'bg-ink-900 text-cream-50' : 'text-ink-700 hover:bg-cream-200',
          )}
        >
          {tb.label}
        </button>
      ))}
    </div>
  )
}

export function Chip({ active, children, onClick }: { active?: boolean; children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'min-h-10 rounded-full px-4 text-sm font-medium ring-1 transition-colors',
        active ? 'bg-leaf-600 text-white ring-leaf-600' : 'bg-white text-ink-700 ring-cream-200 hover:bg-cream-200',
      )}
    >
      {children}
    </button>
  )
}
