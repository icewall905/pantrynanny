import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Pencil, UserPlus } from 'lucide-react'
import { get, patch, post } from '../../api/client'
import type { AdminUser, Role } from '../../api/types'
import { useToast } from '../../components/Toast'
import { Badge, Button, Card, ErrorState, Field, Input, ListSkeleton, Modal, Select, Toggle } from '../../components/ui'

interface Draft extends Partial<AdminUser> {
  password?: string
}

export default function AdminUsers() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['admin', 'users'], queryFn: () => get<AdminUser[]>('/users') })
  const [edit, setEdit] = useState<Draft | null>(null)
  const save = useMutation({
    mutationFn: (d: Draft) => {
      const body: Record<string, unknown> = { display_name: d.display_name, role: d.role ?? 'member', is_active: d.is_active ?? true }
      if (d.password) body.password = d.password
      return d.id ? patch(`/users/${d.id}`, body) : post('/users', { ...body, username: d.username })
    },
    onSuccess: () => {
      setEdit(null)
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] })
      toast.push(t('common.saved'), 'success')
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <ListSkeleton rows={3} />
  const creating = edit && !edit.id
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-bold">{t('admin.tab_users')}</h2>
        <Button size="sm" variant="primary" onClick={() => setEdit({ role: 'member', is_active: true })}>
          <UserPlus className="size-4" /> {t('admin.newUser')}
        </Button>
      </div>
      <ul className="divide-y divide-cream-100">
        {q.data.map((u) => (
          <li key={u.id} className="flex items-center gap-3 py-3">
            <div className="min-w-0 flex-1">
              <div className="font-semibold">{u.display_name}</div>
              <div className="text-xs text-ink-500">{u.username}</div>
            </div>
            <Badge tone={u.role === 'member' ? 'neutral' : 'good'}>{t(`roles.${u.role}`)}</Badge>
            {u.is_active === false && <Badge tone="bad">{t('admin.inactive')}</Badge>}
            <Button size="sm" variant="ghost" aria-label={t('common.edit')} onClick={() => setEdit({ ...u })}>
              <Pencil className="size-4" />
            </Button>
          </li>
        ))}
      </ul>
      <Modal
        open={!!edit}
        onClose={() => setEdit(null)}
        title={creating ? t('admin.newUser') : t('common.edit')}
        footer={
          <>
            <Button onClick={() => setEdit(null)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              loading={save.isPending}
              disabled={!edit?.display_name?.trim() || (!!creating && (!edit?.username?.trim() || !edit?.password))}
              onClick={() => edit && save.mutate(edit)}
            >
              {t('common.save')}
            </Button>
          </>
        }
      >
        {edit && (
          <div className="space-y-3">
            {creating && <Field label={t('login.username')}>{(id) => <Input id={id} autoCapitalize="none" value={edit.username ?? ''} onChange={(e) => setEdit({ ...edit, username: e.target.value })} />}</Field>}
            <Field label={t('admin.displayName')}>{(id) => <Input id={id} value={edit.display_name ?? ''} onChange={(e) => setEdit({ ...edit, display_name: e.target.value })} />}</Field>
            <Field label={creating ? t('login.password') : t('admin.newPassword')} hint={creating ? undefined : t('admin.newPasswordHint')}>
              {(id) => <Input id={id} type="password" autoComplete="new-password" value={edit.password ?? ''} onChange={(e) => setEdit({ ...edit, password: e.target.value })} />}
            </Field>
            <Field label={t('admin.role')}>
              {(id) => (
                <Select id={id} value={edit.role} onChange={(e) => setEdit({ ...edit, role: e.target.value as Role })}>
                  {(['member', 'admin', 'owner'] as Role[]).map((r) => (
                    <option key={r} value={r}>
                      {t(`roles.${r}`)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {!creating && <Toggle checked={edit.is_active !== false} onChange={(v) => setEdit({ ...edit, is_active: v })} label={t('admin.active')} />}
          </div>
        )}
      </Modal>
    </Card>
  )
}
