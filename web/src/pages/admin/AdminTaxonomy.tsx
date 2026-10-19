import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Pencil, Plus, Star, Trash2 } from 'lucide-react'
import { del, get, patch, post } from '../../api/client'
import type { Category, Location } from '../../api/types'
import { useToast } from '../../components/Toast'
import { apiErrorText } from '../../lib/opError'
import { Badge, Button, Card, Field, Input, Modal, Toggle } from '../../components/ui'

type Kind = 'locations' | 'categories'
type Item = Location & Category

function Section({ kind }: { kind: Kind }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const toast = useToast()
  const list = useQuery({ queryKey: [kind, 'admin'], queryFn: () => get<Item[]>(`/${kind}`) })
  const [edit, setEdit] = useState<Partial<Item> | null>(null)
  const [confirm, setConfirm] = useState<Item | null>(null)
  const done = () => {
    void qc.invalidateQueries({ queryKey: [kind] })
    void qc.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const save = useMutation({
    mutationFn: (v: Partial<Item>) => {
      const body = kind === 'locations'
        ? { name: v.name, icon: v.icon || null, is_default: !!v.is_default }
        : { name: v.name, icon: v.icon || null, color: v.color || null }
      return v.id ? patch(`/${kind}/${v.id}`, body) : post(`/${kind}`, body)
    },
    onSuccess: () => {
      setEdit(null)
      done()
      toast.push(t('common.saved'), 'success')
    },
    onError: (e) => toast.push(apiErrorText(t, e, t('common.saveFailed')), 'error'),
  })
  const remove = useMutation({
    mutationFn: (id: string) => del(`/${kind}/${id}`),
    onSuccess: () => {
      setConfirm(null)
      done()
    },
    onError: (e) => toast.push(apiErrorText(t, e, t('common.saveFailed')), 'error'),
  })
  const rows = (list.data ?? []).filter((i) => !i.deleted_at)
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-bold">{t(`admin.${kind}`)}</h2>
        <Button size="sm" variant="primary" onClick={() => setEdit({ name: '' })}>
          <Plus className="size-4" /> {t('common.add')}
        </Button>
      </div>
      <ul className="divide-y divide-cream-100">
        {rows.map((i) => (
          <li key={i.id} className="flex items-center gap-2 py-2">
            <span className="flex-1 font-medium">{i.name}</span>
            {kind === 'locations' && i.is_default && (
              <Badge tone="good">
                <Star className="size-3" /> {t('admin.default')}
              </Badge>
            )}
            <Button size="sm" variant="ghost" aria-label={t('common.edit')} onClick={() => setEdit(i)}>
              <Pencil className="size-4" />
            </Button>
            <Button size="sm" variant="ghost" aria-label={t('common.delete')} onClick={() => setConfirm(i)}>
              <Trash2 className="size-4" />
            </Button>
          </li>
        ))}
      </ul>
      <Modal
        open={!!edit}
        onClose={() => setEdit(null)}
        title={edit?.id ? t('common.edit') : t('common.add')}
        footer={
          <>
            <Button onClick={() => setEdit(null)}>{t('common.cancel')}</Button>
            <Button variant="primary" disabled={!edit?.name?.trim()} loading={save.isPending} onClick={() => edit && save.mutate(edit)}>
              {t('common.save')}
            </Button>
          </>
        }
      >
        {edit && (
          <div className="space-y-3">
            <Field label={t('product.name')}>{(id) => <Input id={id} autoFocus value={edit.name ?? ''} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />}</Field>
            {kind === 'locations' ? (
              <Toggle checked={!!edit.is_default} onChange={(v) => setEdit({ ...edit, is_default: v })} label={t('admin.defaultLocation')} hint={t('admin.defaultLocationHint')} />
            ) : (
              <Field label={t('admin.color')}>{(id) => <Input id={id} type="color" value={edit.color ?? '#2f9a5c'} onChange={(e) => setEdit({ ...edit, color: e.target.value })} />}</Field>
            )}
          </div>
        )}
      </Modal>
      <Modal
        open={!!confirm}
        onClose={() => setConfirm(null)}
        title={t('common.delete')}
        footer={
          <>
            <Button onClick={() => setConfirm(null)}>{t('common.cancel')}</Button>
            <Button variant="danger" loading={remove.isPending} onClick={() => confirm && remove.mutate(confirm.id)}>
              {t('common.delete')}
            </Button>
          </>
        }
      >
        <p className="text-sm">{t('admin.deleteConfirm', { name: confirm?.name })}</p>
      </Modal>
    </Card>
  )
}

export default function AdminTaxonomy() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Section kind="locations" />
      <Section kind="categories" />
    </div>
  )
}
