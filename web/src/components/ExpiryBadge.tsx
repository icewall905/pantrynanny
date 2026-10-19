import { CalendarClock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Badge } from './ui'
import { daysUntil, expiryState, formatDate } from '../lib/format'
import { useSettings } from '../auth/AuthProvider'

export function ExpiryBadge({ date }: { date: string | null | undefined }) {
  const { t, i18n } = useTranslation()
  const { expiry_soon_days } = useSettings()
  const state = expiryState(date, expiry_soon_days)
  if (!date || state === 'none') return null
  const n = daysUntil(date)
  const label =
    state === 'expired'
      ? t('expiry.expired')
      : n === 0
        ? t('expiry.today')
        : state === 'soon'
          ? t('expiry.inDays', { count: n })
          : formatDate(date, i18n.language)
  return (
    <Badge tone={state === 'expired' ? 'bad' : state === 'soon' ? 'warn' : 'neutral'}>
      <CalendarClock className="size-3.5" aria-hidden />
      <span title={formatDate(date, i18n.language)}>{label}</span>
    </Badge>
  )
}
