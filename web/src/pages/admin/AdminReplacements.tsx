import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Check, Sparkles, Trash2, X } from 'lucide-react'
import { del, get, post } from '../../api/client'
import type { Product, UUID } from '../../api/types'
import { useToast } from '../../components/Toast'
import { Badge, Button, Card, ErrorState, ListSkeleton, Select } from '../../components/ui'

type Kind = 'same' | 'swap'
interface Miss {
  ingredient: string
  example: string
  recipes: number
}
interface Substitute {
  id: UUID
  ingredient: string
  product_id: UUID
  product_name: string
  source: 'manual' | 'ai'
}
interface Overview {
  misses: Miss[]
  substitutes: Substitute[]
}
interface Suggestion {
  ingredient: string
  product_id: UUID
  product_name: string
  kind: Kind
  reason: string
}

const KEY = ['admin', 'replacements']

export default function AdminReplacements() {
  const { t, i18n } = useTranslation()
  const toast = useToast()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: KEY, queryFn: () => get<Overview>('/admin/replacements') })
  const products = useQuery({ queryKey: ['products', 'all'], queryFn: () => get<Product[]>('/products?limit=200') })
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(null)
  const [pick, setPick] = useState<Record<string, string>>({})

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: KEY })
    void qc.invalidateQueries({ queryKey: ['recipes'] })
    void qc.invalidateQueries({ queryKey: ['recipe'] })
  }
  const approve = useMutation({
    mutationFn: (b: { ingredient: string; product_id: UUID; kind: Kind; source: 'manual' | 'ai' }) =>
      post<{ result: string }>('/admin/replacements', b),
    onSuccess: (_, b) => {
      toast.push(t('replacements.saved'), 'success')
      setSuggestions((s) => s?.filter((x) => !(x.ingredient === b.ingredient && x.product_id === b.product_id)) ?? null)
      refresh()
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  const remove = useMutation({
    mutationFn: (id: UUID) => del(`/admin/replacements/${id}`),
    onSuccess: refresh,
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  const suggest = useMutation({
    mutationFn: () => post<Suggestion[]>('/admin/replacements/suggest', { locale: i18n.language.startsWith('da') ? 'da' : 'en' }),
    onSuccess: (s) => {
      setSuggestions(s)
      if (!s.length) toast.push(t('replacements.noSuggestions'), 'info')
    },
    onError: (e) => toast.push(e instanceof Error ? e.message : t('replacements.aiFailed'), 'error'),
  })

  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <ListSkeleton rows={6} />
  const { misses, substitutes } = q.data
  const manual = (m: Miss, kind: Kind) => {
    const pid = pick[m.ingredient]
    if (pid) approve.mutate({ ingredient: m.example, product_id: pid, kind, source: 'manual' })
  }

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold">{t('replacements.title')}</h2>
            <p className="text-sm text-ink-500">{t('replacements.hint')}</p>
          </div>
          <Button variant="primary" loading={suggest.isPending} disabled={!misses.length} onClick={() => suggest.mutate()} data-testid="replacements-suggest">
            <Sparkles className="size-4" /> {t('replacements.suggest')}
          </Button>
        </div>
      </Card>

      {suggestions && suggestions.length > 0 && (
        <Card>
          <h3 className="mb-2 font-semibold">{t('replacements.suggestions')}</h3>
          <ul className="divide-y divide-cream-200" data-testid="replacement-suggestions">
            {suggestions.map((s) => (
              <li key={`${s.ingredient}|${s.product_id}`} className="flex flex-wrap items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">
                    {s.ingredient} → {s.product_name}
                  </div>
                  {s.reason && <div className="text-xs text-ink-500">{s.reason}</div>}
                </div>
                <Badge tone={s.kind === 'same' ? 'good' : 'warn'}>{t(`replacements.kind_${s.kind}`)}</Badge>
                <Button size="sm" variant="primary" aria-label={t('replacements.approve')} onClick={() => approve.mutate({ ...s, source: 'ai' })}>
                  <Check className="size-4" />
                </Button>
                <Button size="sm" variant="ghost" aria-label={t('replacements.reject')} onClick={() => setSuggestions((x) => x?.filter((y) => y !== s) ?? null)}>
                  <X className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <h3 className="mb-1 font-semibold">{t('replacements.misses')}</h3>
        <p className="mb-2 text-sm text-ink-500">{t('replacements.missesHint')}</p>
        {misses.length === 0 ? (
          <p className="text-sm text-ink-500">{t('replacements.noMisses')}</p>
        ) : (
          <ul className="divide-y divide-cream-200" data-testid="replacement-misses">
            {misses.map((m) => (
              <li key={m.ingredient} className="flex flex-wrap items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{m.example}</div>
                  <div className="text-xs text-ink-500">{t('replacements.inRecipes', { count: m.recipes })}</div>
                </div>
                <Select
                  className="w-auto min-w-40"
                  value={pick[m.ingredient] ?? ''}
                  onChange={(e) => setPick((p) => ({ ...p, [m.ingredient]: e.target.value }))}
                  aria-label={t('replacements.product')}
                >
                  <option value="">{t('replacements.product')}</option>
                  {(products.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
                <Button size="sm" disabled={!pick[m.ingredient]} onClick={() => manual(m, 'same')}>
                  {t('replacements.kind_same')}
                </Button>
                <Button size="sm" disabled={!pick[m.ingredient]} onClick={() => manual(m, 'swap')}>
                  {t('replacements.kind_swap')}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <h3 className="mb-2 font-semibold">{t('replacements.approved')}</h3>
        {substitutes.length === 0 ? (
          <p className="text-sm text-ink-500">{t('replacements.noApproved')}</p>
        ) : (
          <ul className="divide-y divide-cream-200">
            {substitutes.map((s) => (
              <li key={s.id} className="flex items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  {s.ingredient} → {s.product_name}
                </div>
                {s.source === 'ai' && <Badge tone="info">AI</Badge>}
                <Button size="sm" variant="ghost" aria-label={t('common.delete')} onClick={() => remove.mutate(s.id)}>
                  <Trash2 className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
