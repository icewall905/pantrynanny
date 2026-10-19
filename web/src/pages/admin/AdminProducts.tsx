import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { GitMerge, Pencil, Search } from 'lucide-react'
import { get, patch, post, qs } from '../../api/client'
import type { Product } from '../../api/types'
import { conflictProduct, ProductForm } from '../../components/ProductForm'
import { ProductThumb } from '../../components/ProductThumb'
import { useToast } from '../../components/Toast'
import { Badge, Button, Card, ErrorState, Input, ListSkeleton, Modal } from '../../components/ui'
import { useDebounced } from '../../hooks/useDebounced'

export default function AdminProducts() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const toast = useToast()
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const [edit, setEdit] = useState<Product | null>(null)
  const [conflict, setConflict] = useState<Product | null>(null)
  const [merge, setMerge] = useState<Product | null>(null)
  const [target, setTarget] = useState('')
  const dt = useDebounced(target)

  const list = useQuery({ queryKey: ['products', { q: dq, admin: true }], queryFn: () => get<Product[]>(`/products${qs({ q: dq, limit: 100 })}`) })
  const cand = useQuery({
    queryKey: ['products', { q: dt, merge: true }],
    queryFn: () => get<Product[]>(`/products${qs({ q: dt, limit: 8 })}`),
    enabled: !!merge && dt.length >= 2,
  })
  const refresh = () => void qc.invalidateQueries({ queryKey: ['products'] })

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      patch<Product>(`/products/${edit!.id}`, body, { headers: { 'If-Match': String(edit!.version) } }),
    onSuccess: () => {
      setEdit(null)
      setConflict(null)
      refresh()
      toast.push(t('common.saved'), 'success')
    },
    onError: (e) => {
      const c = conflictProduct(e)
      if (c) setConflict(c)
      else toast.push(t('common.saveFailed'), 'error')
    },
  })
  const doMerge = useMutation({
    mutationFn: (into: string) => post(`/products/${merge!.id}/merge`, { into_id: into }),
    onSuccess: () => {
      setMerge(null)
      setTarget('')
      refresh()
      void qc.invalidateQueries({ queryKey: ['inventory'] })
      toast.push(t('admin.merged'), 'success')
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })

  return (
    <>
      <div className="relative mb-4">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-ink-500" />
        <Input aria-label={t('inventory.search')} placeholder={t('inventory.searchPlaceholder')} value={q} onChange={(e) => setQ(e.target.value)} className="pl-10" />
      </div>
      {list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.isLoading ? (
        <ListSkeleton />
      ) : (
        <Card className="overflow-x-auto p-0 sm:p-0">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="border-b border-cream-200 text-xs uppercase text-ink-500">
              <tr>
                <th className="p-3">{t('product.name')}</th>
                <th className="p-3">{t('product.barcodes')}</th>
                <th className="p-3">{t('admin.status')}</th>
                <th className="p-3" />
              </tr>
            </thead>
            <tbody>
              {list.data?.map((p) => (
                <tr key={p.id} className="border-b border-cream-100 last:border-0">
                  <td className="p-3">
                    <Link to={`/products/${p.id}`} className="flex items-center gap-3 font-semibold">
                      <ProductThumb name={p.name} src={p.image_url} className="size-10 text-base" />
                      <span>
                        {p.name}
                        <span className="block text-xs font-normal text-ink-500">{p.brand}</span>
                      </span>
                    </Link>
                  </td>
                  <td className="p-3 text-xs text-ink-500">{p.barcodes.map((b) => b.raw).join(', ')}</td>
                  <td className="p-3">
                    <Badge tone={p.status === 'known' ? 'good' : 'info'}>{t(`status.${p.status}`)}</Badge>
                  </td>
                  <td className="p-3 text-right">
                    <Button size="sm" variant="ghost" aria-label={t('common.edit')} onClick={() => setEdit(p)}>
                      <Pencil className="size-4" />
                    </Button>
                    <Button size="sm" variant="ghost" aria-label={t('admin.merge')} onClick={() => setMerge(p)}>
                      <GitMerge className="size-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Modal open={!!edit} onClose={() => setEdit(null)} title={t('common.edit')}>
        {edit && (
          <ProductForm
            key={conflict?.version ?? edit.version}
            initial={conflict ?? edit}
            conflict={conflict}
            saving={save.isPending}
            onReload={(s) => {
              setEdit(s)
              setConflict(null)
            }}
            onSubmit={(b) => save.mutate(b)}
            onCancel={() => setEdit(null)}
          />
        )}
      </Modal>

      <Modal open={!!merge} onClose={() => setMerge(null)} title={t('admin.mergeTitle', { name: merge?.name })}>
        <p className="mb-3 text-sm text-ink-500">{t('admin.mergeHint')}</p>
        <Input aria-label={t('admin.mergeInto')} placeholder={t('admin.mergeInto')} value={target} onChange={(e) => setTarget(e.target.value)} />
        <ul className="mt-3 space-y-1">
          {cand.data
            ?.filter((p) => p.id !== merge?.id)
            .map((p) => (
              <li key={p.id}>
                <button className="flex min-h-12 w-full items-center gap-3 rounded-xl px-2 text-left hover:bg-cream-100" disabled={doMerge.isPending} onClick={() => doMerge.mutate(p.id)}>
                  <ProductThumb name={p.name} src={p.image_url} className="size-9 text-sm" />
                  <span className="font-medium">{p.name}</span>
                  <span className="text-xs text-ink-500">{p.brand}</span>
                </button>
              </li>
            ))}
        </ul>
      </Modal>
    </>
  )
}
