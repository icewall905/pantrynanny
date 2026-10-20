import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Smartphone, Tablet, Trash2 } from 'lucide-react'
import { del, get, post } from '../../api/client'
import type { DeviceInfo, KioskCode } from '../../api/types'
import { useToast } from '../../components/Toast'
import { Badge, Button, Card, ErrorState, Field, Input, ListSkeleton, Modal } from '../../components/ui'
import DirectScannerLink from '../DirectScannerLink'
import { formatDateTime } from '../../lib/format'

export default function AdminDevices() {
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['admin', 'devices'], queryFn: () => get<DeviceInfo[]>('/devices') })
  const [name, setName] = useState('')
  const [open, setOpen] = useState(false)
  const [code, setCode] = useState<KioskCode | null>(null)
  const revoke = useMutation({
    mutationFn: (id: string) => del(`/devices/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['admin', 'devices'] }),
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  const create = useMutation({
    mutationFn: () => post<KioskCode>('/devices/kiosk-codes', { name: name.trim() }),
    onSuccess: (c) => {
      setCode(c)
      void qc.invalidateQueries({ queryKey: ['admin', 'devices'] })
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  const close = () => {
    setOpen(false)
    setCode(null)
    setName('')
  }
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <ListSkeleton rows={3} />
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-bold">{t('admin.tab_devices')}</h2>
        <Button size="sm" variant="primary" onClick={() => setOpen(true)}>
          <Tablet className="size-4" /> {t('admin.pairKiosk')}
        </Button>
      </div>
      {q.data.length === 0 && <p className="text-sm text-ink-500">{t('admin.none')}</p>}
      <ul className="divide-y divide-cream-100">
        {q.data.map((d) => (
          <li key={d.id} className="flex items-center gap-3 py-3">
            <Smartphone className="size-5 text-ink-500" />
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">{d.device_name ?? d.platform ?? d.id.slice(0, 8)}</div>
              <div className="text-xs text-ink-500">
                {[d.username, d.last_used_at ? formatDateTime(d.last_used_at, i18n.language) : null].filter(Boolean).join(' · ')}
              </div>
            </div>
            {d.kind === 'kiosk' && <Badge tone="info">Kiosk</Badge>}
            {d.current && <Badge tone="good">{t('admin.thisDevice')}</Badge>}
            <Button size="sm" variant="ghost" aria-label={t('admin.revoke')} onClick={() => revoke.mutate(d.id)}>
              <Trash2 className="size-4" /> {t('admin.revoke')}
            </Button>
          </li>
        ))}
      </ul>
      <div className="mt-4 border-t border-cream-100 pt-4">
        <DirectScannerLink />
      </div>
      <Modal
        open={open}
        onClose={close}
        title={t('admin.pairKiosk')}
        footer={
          code ? (
            <Button variant="primary" onClick={close}>
              {t('common.close')}
            </Button>
          ) : (
            <>
              <Button onClick={close}>{t('common.cancel')}</Button>
              <Button variant="primary" disabled={!name.trim()} loading={create.isPending} onClick={() => create.mutate()}>
                {t('admin.createCode')}
              </Button>
            </>
          )
        }
      >
        {code ? (
          <div className="py-4 text-center">
            <div data-testid="kiosk-code" className="select-all font-mono text-5xl font-extrabold tracking-[0.2em] text-leaf-700">
              {code.code}
            </div>
            <p className="mt-4 text-sm text-ink-700">{t('admin.kioskInstructions', { url: `${window.location.host}/scan` })}</p>
            <p className="mt-1 text-xs text-ink-500">{t('admin.kioskExpires', { time: formatDateTime(code.expires_at, i18n.language) })}</p>
          </div>
        ) : (
          <Field label={t('admin.deviceName')}>{(id) => <Input id={id} autoFocus placeholder="iPad køkken" value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        )}
      </Modal>
    </Card>
  )
}
