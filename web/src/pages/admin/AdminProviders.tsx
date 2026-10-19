import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { get, patch } from '../../api/client'
import type { ProviderInfo } from '../../api/types'
import { useToast } from '../../components/Toast'
import { Button, Card, ErrorState, Input, ListSkeleton, Toggle } from '../../components/ui'

function Row({ p }: { p: ProviderInfo }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const toast = useToast()
  const [enabled, setEnabled] = useState(p.enabled)
  const [key, setKey] = useState('')
  const save = useMutation({
    mutationFn: () =>
      patch('/admin/providers', { providers: [{ name: p.id ?? p.name, enabled, ...(key ? { api_key: key } : {}) }] }),
    onSuccess: () => {
      setKey('')
      void qc.invalidateQueries({ queryKey: ['admin', 'providers'] })
      toast.push(t('common.saved'), 'success')
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  return (
    <li className="space-y-2 py-3">
      <Toggle checked={enabled} onChange={setEnabled} label={p.name} />
      {p.requires_key !== false && (
        <Input
          type="password"
          autoComplete="off"
          aria-label={`${p.name} API`}
          placeholder={p.has_key || p.api_key ? (p.api_key ?? '••••••••') : t('admin.apiKey')}
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
      )}
      <Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
        {t('common.save')}
      </Button>
    </li>
  )
}

export default function AdminProviders() {
  const { t } = useTranslation()
  const q = useQuery({
    queryKey: ['admin', 'providers'],
    queryFn: async () => {
      const r = await get<ProviderInfo[] | { providers: ProviderInfo[] }>('/admin/providers')
      return Array.isArray(r) ? r : r.providers
    },
  })
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <ListSkeleton rows={3} />
  return (
    <Card>
      <h2 className="text-lg font-bold">{t('admin.tab_providers')}</h2>
      <p className="mb-2 text-sm text-ink-500">{t('admin.providersHint')}</p>
      <ul className="divide-y divide-cream-100">
        {q.data.map((p) => (
          <Row key={p.id ?? p.name} p={p} />
        ))}
      </ul>
    </Card>
  )
}
