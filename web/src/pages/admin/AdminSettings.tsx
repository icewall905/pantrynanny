import { useState } from 'react'
import { RotateCcw, X } from 'lucide-react'
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
    // staples have their own editor (below): never send a stale copy from here
    mutationFn: () => {
      const { staples: _s, default_staples: _d, ...body } = s
      return patch<HouseholdSettings>('/settings', body)
    },
    onSuccess: (res) => {
      if (me) qc.setQueryData(keys.me, { ...me, settings: { ...me.settings, ...s, ...res } })
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
    <div className="space-y-4">
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
    <StaplesEditor />
    </div>
  )
}

/** "Always in the house" for recipes: add/remove chips, saved right away (admin only). */
function StaplesEditor() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const toast = useToast()
  const { me } = useAuth()
  const current = useSettings()
  const list = current.staples ?? []
  const [text, setText] = useState('')
  const save = useMutation({
    mutationFn: (staples: string[] | null) => patch<HouseholdSettings>('/settings', { staples }),
    onSuccess: (res) => {
      if (me) qc.setQueryData(keys.me, { ...me, settings: { ...me.settings, ...res } })
      void qc.invalidateQueries({ queryKey: ['recipes'] })
      setText('')
    },
    onError: (e) => toast.push(apiErrorText(t, e, t('common.saveFailed')), 'error'),
  })
  const add = () => {
    const v = text.trim().toLowerCase()
    if (!v) return
    if (list.includes(v)) return setText('')
    save.mutate([...list, v])
  }
  const isDefault =
    !!current.default_staples && list.length === current.default_staples.length && list.every((x) => current.default_staples!.includes(x))
  return (
    <Card className="max-w-xl space-y-3" data-testid="staples-editor">
      <div>
        <h2 className="text-lg font-bold">{t('admin.staples')}</h2>
        <p className="text-sm text-ink-500">{t('admin.staplesHint')}</p>
      </div>
      <ul className="flex flex-wrap gap-2">
        {list.map((x) => (
          <li key={x} className="inline-flex items-center gap-1 rounded-full bg-cream-200 py-1 pl-3 pr-1 text-sm font-medium">
            {x}
            <button
              type="button"
              aria-label={t('admin.staplesRemove', { name: x })}
              disabled={save.isPending}
              onClick={() => save.mutate(list.filter((y) => y !== x))}
              className="grid size-7 place-items-center rounded-full hover:bg-cream-100"
            >
              <X className="size-3.5" />
            </button>
          </li>
        ))}
      </ul>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          add()
        }}
      >
        <Input value={text} maxLength={80} onChange={(e) => setText(e.target.value)} placeholder={t('admin.staplesAdd')} aria-label={t('admin.staplesAdd')} />
        <Button type="submit" variant="primary" loading={save.isPending} disabled={!text.trim()}>
          {t('common.add')}
        </Button>
      </form>
      <Button size="sm" variant="ghost" disabled={isDefault || save.isPending} onClick={() => save.mutate(null)}>
        <RotateCcw className="size-4" /> {t('admin.staplesReset')}
      </Button>
    </Card>
  )
}
