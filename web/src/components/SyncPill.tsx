import { CheckCircle2, CloudOff, Loader2, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { syncNow, useSyncStatus } from '../offline'
import { cn } from '../lib/format'

export function SyncPill({ className }: { className?: string }) {
  const { t } = useTranslation()
  const s = useSyncStatus()
  let Icon = CheckCircle2
  let label = t('sync.synced')
  let tone = 'bg-leaf-50 text-leaf-700'
  if (!s.online) {
    Icon = CloudOff
    label = s.pending ? t('sync.offlinePending', { count: s.pending }) : t('sync.offline')
    tone = 'bg-honey-50 text-honey-600'
  } else if (s.syncing) {
    Icon = Loader2
    label = t('sync.syncing')
    tone = 'bg-sky-500/10 text-sky-500'
  } else if (s.pending > 0) {
    Icon = RefreshCw
    label = t('sync.pending', { count: s.pending })
    tone = 'bg-honey-50 text-honey-600'
  } else if (s.error) {
    Icon = RefreshCw
    label = t('sync.error')
    tone = 'bg-tomato-50 text-tomato-600'
  }
  return (
    <button
      type="button"
      onClick={() => void syncNow()}
      title={t('sync.syncNow')}
      className={cn('inline-flex min-h-9 items-center gap-1.5 rounded-full px-3 text-xs font-semibold', tone, className)}
    >
      <Icon className={cn('size-4', s.syncing && 'animate-spin')} aria-hidden />
      <span>{label}</span>
    </button>
  )
}
