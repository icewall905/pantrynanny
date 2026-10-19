import { Minus, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { formatQty } from '../lib/format'

export function QuantityStepper({
  value,
  unit,
  onChange,
  disableMinus,
  name,
}: {
  value: number
  unit?: string
  onChange: (delta: number) => void
  disableMinus?: boolean
  name: string
}) {
  const { t, i18n } = useTranslation()
  return (
    <div className="flex items-center gap-1 rounded-2xl bg-cream-100 p-1">
      <button
        type="button"
        aria-label={t('inventory.decrease', { name })}
        disabled={disableMinus ?? value <= 0}
        onClick={() => onChange(-1)}
        className="grid size-11 place-items-center rounded-xl bg-surface shadow-sm transition active:scale-95 disabled:opacity-40"
      >
        <Minus className="size-5" />
      </button>
      <div className="min-w-12 px-1 text-center" aria-live="polite">
        <span className="text-lg font-bold tabular-nums">{formatQty(value, i18n.language)}</span>
        {unit && <span className="block text-[10px] leading-none text-ink-500">{unit}</span>}
      </div>
      <button
        type="button"
        aria-label={t('inventory.increase', { name })}
        onClick={() => onChange(1)}
        className="grid size-11 place-items-center rounded-xl bg-leaf-600 text-white shadow-sm transition active:scale-95"
      >
        <Plus className="size-5" />
      </button>
    </div>
  )
}
