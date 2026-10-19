import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { BookOpen, Clock, Link2, Plus, Sparkles } from 'lucide-react'
import { get, post } from '../../api/client'
import { totalMinutes, type RecipeDraft, type RecipeSummary } from '../../api/recipes'
import { Badge, Button, Card, Chip, EmptyState, ErrorState, Field, Input, ListSkeleton, Modal, PageHeader, Tabs } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { ApiError } from '../../api/client'
import { cn } from '../../lib/format'

type Tab = 'cook' | 'all'
const TIMES = [null, 30, 60] as const

export default function RecipesPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('cook')
  const [maxMin, setMaxMin] = useState<number | null>(null)
  const [q, setQ] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const suggest = useQuery({
    queryKey: ['recipes', 'suggest', maxMin],
    queryFn: () => get<RecipeSummary[]>(`/recipes/suggest${maxMin ? `?max_minutes=${maxMin}` : ''}`),
    enabled: tab === 'cook',
  })
  const all = useQuery({
    queryKey: ['recipes', 'all', q],
    queryFn: () => get<RecipeSummary[]>(`/recipes${q ? `?q=${encodeURIComponent(q)}` : ''}`),
    enabled: tab === 'all',
  })
  const data = tab === 'cook' ? suggest : all
  return (
    <>
      <PageHeader
        title={t('recipes.title')}
        subtitle={t('recipes.subtitle')}
        actions={
          <>
            <Button onClick={() => setImportOpen(true)}>
              <Link2 className="size-4" /> {t('recipes.import')}
            </Button>
            <Link to="/recipes/new" className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-leaf-600 px-4 text-sm font-semibold text-white hover:bg-leaf-800">
              <Plus className="size-4" /> {t('recipes.new')}
            </Link>
          </>
        }
      />
      <Tabs
        tabs={[
          { id: 'cook', label: t('recipes.tabCook') },
          { id: 'all', label: t('recipes.tabAll') },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'cook' ? (
        <div className="mb-4 flex flex-wrap gap-2">
          {TIMES.map((m) => (
            <Chip key={m ?? 'any'} active={maxMin === m} onClick={() => setMaxMin(m)}>
              {m ? t('recipes.maxMin', { n: m }) : t('recipes.anyTime')}
            </Chip>
          ))}
        </div>
      ) : (
        <Input className="mb-4" placeholder={t('recipes.search')} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t('recipes.search')} />
      )}
      {data.isError ? (
        <ErrorState error={data.error} onRetry={() => void data.refetch()} />
      ) : !data.data ? (
        <ListSkeleton rows={4} />
      ) : data.data.length === 0 ? (
        <EmptyState icon={<BookOpen />} title={t('recipes.empty')} hint={t('recipes.emptyHint')} />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2" data-testid="recipe-list">
          {data.data.map((s) => (
            <li key={s.recipe.id}>
              <RecipeCard s={s} />
            </li>
          ))}
        </ul>
      )}
      <ImportDialog open={importOpen} onClose={() => setImportOpen(false)} />
    </>
  )
}

function RecipeCard({ s }: { s: RecipeSummary }) {
  const { t } = useTranslation()
  const { recipe: r, availability: a } = s
  const mins = totalMinutes(r)
  const ready = a.missing === 0
  return (
    <Link to={`/recipes/${r.id}`} className="block h-full">
      <Card className="h-full transition hover:-translate-y-0.5 hover:ring-leaf-500/40">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold">{r.title}</h2>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-sm text-ink-500">
              {mins > 0 && (
                <span className="inline-flex items-center gap-1">
                  <Clock className="size-3.5" /> {t('recipes.minutes', { n: mins })}
                </span>
              )}
              <span>{t('recipes.servings', { count: r.servings })}</span>
            </div>
          </div>
          <Badge tone={ready ? 'good' : a.coverage >= 0.6 ? 'warn' : 'neutral'}>
            {ready ? t('recipes.ready') : t('recipes.missingN', { count: a.missing })}
          </Badge>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-cream-200" aria-hidden>
          <div className={cn('h-full rounded-full', ready ? 'bg-leaf-500' : 'bg-honey-400')} style={{ width: `${Math.round(a.coverage * 100)}%` }} />
        </div>
        <p className="mt-1.5 text-xs text-ink-500">{t('recipes.coverage', { have: a.have, of: a.required })}</p>
        {a.uses_expiring.length > 0 && (
          <p className="mt-2 flex items-center gap-1.5 text-sm text-honey-600">
            <Sparkles className="size-4" /> {t('recipes.usesExpiring', { names: a.uses_expiring.join(', ') })}
          </p>
        )}
      </Card>
    </Link>
  )
}

function ImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const nav = useNavigate()
  const toast = useToast()
  const [url, setUrl] = useState('')
  const run = useMutation({
    mutationFn: () => post<RecipeDraft>('/recipes/import', { url: url.trim() }),
    onSuccess: (draft) => {
      onClose()
      nav('/recipes/new', { state: { draft } })
    },
    onError: (e) => toast.push(e instanceof ApiError ? e.message : t('recipes.importFailed'), 'error'),
  })
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('recipes.importTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={run.isPending} disabled={!/^https?:\/\/.+/.test(url.trim())} onClick={() => run.mutate()}>
            {t('recipes.importGo')}
          </Button>
        </>
      }
    >
      <Field label={t('recipes.importUrl')} hint={t('recipes.importHint')}>
        {(id) => <Input id={id} inputMode="url" autoCapitalize="none" placeholder="https://" value={url} onChange={(e) => setUrl(e.target.value)} />}
      </Field>
    </Modal>
  )
}
