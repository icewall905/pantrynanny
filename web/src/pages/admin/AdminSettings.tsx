import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { patch } from '../../api/client'
import { keys } from '../../api/queries'
import type { HouseholdSettings } from '../../api/types'
import { useAuth, useSettings } from '../../auth/AuthProvider'
import { useToast } from '../../components/Toast'
import { apiErrorText } from '../../lib/opError'
import { Button, Card, Field, Input, Select, Toggle } from '../../components/ui'

export default function AdminSettings() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const toast = useToast()
  const { me } = useAuth()
  const current = useSettings()
  const [s, setS] = useState<HouseholdSettings>(current)
  const save = useMutation({
    mutationFn: () => patch<HouseholdSettings>('/settings', { ...s }),
    onSuccess: (res) => {
      if (me) qc.setQueryData(keys.me, { ...me, settings: { ...s, ...res } })
      void qc.invalidateQueries({ queryKey: ['inventory'] })
      toast.push(t('common.saved'), 'success')
    },
    onError: (e) => toast.push(apiErrorText(t, e, t('common.saveFailed')), 'error'),
  })
  const numField = (k: 'expiry_soon_days' | 'remove_mode_timeout_min' | 'scan_rearm_ms', label: string, min: number, max: number, hint?: string) => (
    <Field label={label} hint={hint}>
      {(id) => <Input id={id} type="number" min={min} max={max} value={s[k]} onChange={(e) => setS({ ...s, [k]: Number(e.target.value) })} />}
    </Field>
  )
  return (
    <Card className="max-w-xl space-y-4">
      <h2 className="text-lg font-bold">{t('admin.tab_settings')}</h2>
      <Field label={t('admin.locale')}>
        {(id) => (
          <Select id={id} value={s.locale} onChange={(e) => setS({ ...s, locale: e.target.value as 'da' | 'en' })}>
            <option value="da">Dansk</option>
            <option value="en">English</option>
          </Select>
        )}
      </Field>
      <Toggle checked={s.allow_negative_stock} onChange={(v) => setS({ ...s, allow_negative_stock: v })} label={t('admin.allowNegative')} hint={t('admin.allowNegativeHint')} />
      <Toggle checked={s.auto_shopping_low_stock} onChange={(v) => setS({ ...s, auto_shopping_low_stock: v })} label={t('admin.autoShopping')} hint={t('admin.autoShoppingHint')} />
      {numField('expiry_soon_days', t('admin.expirySoonDays'), 0, 365)}
      {numField('remove_mode_timeout_min', t('admin.removeTimeout'), 1, 240, t('admin.removeTimeoutHint'))}
      {numField('scan_rearm_ms', t('admin.rearm'), 250, 3000, t('admin.rearmHint'))}
      <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
        {t('common.save')}
      </Button>
    </Card>
  )
}
