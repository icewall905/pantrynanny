import { useDeferredValue, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { BookOpen, ChevronLeft, ChevronRight, Clock, Link2, Plus, Sparkles } from 'lucide-react'
import { get, post, qs } from '../../api/client'
import { COURSES, totalMinutes, type Course, type RecipeDraft, type RecipeSummary } from '../../api/recipes'
import { Badge, Button, Card, Chip, EmptyState, ErrorState, Field, Input, ListSkeleton, Modal, PageHeader, Tabs } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { ApiError } from '../../api/client'
import { cn } from '../../lib/format'
import { categoriesOf, inCategory, isAntiInflammatory, matchesRecipe, pageOf } from '../../lib/recipeSearch'

type Tab = 'cook' | 'all'
const TIMES = [null, 30, 60] as const

export default function RecipesPage() {
  const { t } = useTranslation()
  // Filters and page live in the URL, so coming back from a recipe lands where you were.
  const [sp, setSp] = useSearchParams()
  const put = (key: string, value: string | null, keepPage = false) =>
    setSp(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(key, value)
        else next.delete(key)
        if (!keepPage) next.delete('page') // any filter change starts over on page 1
        return next
      },
      { replace: true },
    )
  const tab: Tab = sp.get('tab') === 'all' ? 'all' : 'cook'
  const setTab = (v: Tab) => put('tab', v === 'all' ? 'all' : null)
  const maxMin = Number(sp.get('max')) || null
  const setMaxMin = (v: number | null) => put('max', v ? String(v) : null)
  const course = (COURSES as string[]).includes(sp.get('course') ?? '') ? (sp.get('course') as Course) : null
  const setCourse = (v: Course | null) => put('course', v)
  const q = sp.get('q') ?? ''
  const setQ = (v: string) => put('q', v || null)
  const find = sp.get('find') ?? ''
  const setFind = (v: string) => put('find', v || null)
  const category = sp.get('cat')
  const setCategory = (v: string | null) => put('cat', v)
  const pageParam = Math.max(0, (Number(sp.get('page')) || 1) - 1)
  // remembered on this device: a standing diet choice, not a one-off filter
  const [antiInfl, setAntiInflState] = useState(() => {
    try {
      return localStorage.getItem('pn.recipes.antiInflammatory') === '1'
    } catch {
      return false
    }
  })
  const setAntiInfl = (v: boolean) => {
    setAntiInflState(v)
    try {
      localStorage.setItem('pn.recipes.antiInflammatory', v ? '1' : '0')
    } catch {
      /* private mode: just not remembered */
    }
    put('page', null)
  }
  const findLive = useDeferredValue(find)
  const [importOpen, setImportOpen] = useState(false)
  const suggest = useQuery({
    queryKey: ['recipes', 'suggest', maxMin, course],
    queryFn: () => get<RecipeSummary[]>(`/recipes/suggest${qs({ max_minutes: maxMin, course })}`),
    enabled: tab === 'cook',
  })
  const all = useQuery({
    queryKey: ['recipes', 'all', q],
    queryFn: () => get<RecipeSummary[]>(`/recipes${q ? `?q=${encodeURIComponent(q)}` : ''}`),
    enabled: tab === 'all',
  })
  const data = tab === 'cook' ? suggest : all
  const categories = useMemo(() => categoriesOf(data.data ?? []), [data.data])
  const cat = category && categories.some((c) => c.toLowerCase() === category.toLowerCase()) ? category : null
  const shown = useMemo(
    () =>
      data.data?.filter(
        (s) => inCategory(s, cat) && (!antiInfl || isAntiInflammatory(s)) && (tab !== 'cook' || matchesRecipe(s, findLive, s.recipe.course ? [t(`recipes.course_${s.recipe.course}`)] : [])),
      ),
    [tab, data.data, findLive, cat, antiInfl, t],
  )
  const paged = pageOf(shown ?? [], pageParam)
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
        <>
          <Input
            className="mb-3"
            type="search"
            placeholder={t('recipes.cookSearch')}
            value={find}
            onChange={(e) => setFind(e.target.value)}
            aria-label={t('recipes.cookSearch')}
            data-testid="recipe-cook-search"
          />
          <div className="mb-4 flex flex-wrap gap-2">
          {TIMES.map((m) => (
            <Chip key={m ?? 'any'} active={maxMin === m} onClick={() => setMaxMin(m)}>
              {m ? t('recipes.maxMin', { n: m }) : t('recipes.anyTime')}
            </Chip>
          ))}
          <select
            aria-label={t('recipes.course')}
            value={course ?? ''}
            onChange={(e) => setCourse((e.target.value || null) as Course | null)}
            className={cn('min-h-10 rounded-full px-4 text-sm font-medium ring-1', course ? 'bg-leaf-600 text-white ring-leaf-600' : 'bg-surface text-ink-700 ring-cream-200')}
            data-testid="recipe-course-filter"
          >
            <option value="">{t('recipes.allCourses')}</option>
            {COURSES.map((c) => (
              <option key={c} value={c}>
                {t(`recipes.course_${c}`)}
              </option>
            ))}
          </select>
            <CategorySelect categories={categories} value={cat} onChange={setCategory} />
            <Chip active={antiInfl} onClick={() => setAntiInfl(!antiInfl)}>
              {t('recipes.antiInflammatory')}
            </Chip>
          </div>
        </>
      ) : (
        <div className="mb-4 flex flex-wrap gap-2">
          <Input className="min-w-0 flex-1" placeholder={t('recipes.search')} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t('recipes.search')} />
          <CategorySelect categories={categories} value={cat} onChange={setCategory} />
          <Chip active={antiInfl} onClick={() => setAntiInfl(!antiInfl)}>
            {t('recipes.antiInflammatory')}
          </Chip>
        </div>
      )}
      {data.isError ? (
        <ErrorState error={data.error} onRetry={() => void data.refetch()} />
      ) : !data.data ? (
        <ListSkeleton rows={4} />
      ) : data.data.length > 0 && shown?.length === 0 ? (
        <EmptyState icon={<BookOpen />} title={t('recipes.findEmpty', { q: findLive.trim() })} />
      ) : data.data.length === 0 ? (
        tab === 'cook' ? (
          <EmptyState icon={<BookOpen />} title={t('recipes.cookEmpty')} hint={t('recipes.cookEmptyHint')} />
        ) : (
          <EmptyState icon={<BookOpen />} title={t('recipes.empty')} hint={t('recipes.emptyHint')} />
        )
      ) : (
        <>
          <ul className="grid gap-3 sm:grid-cols-2" data-testid="recipe-list">
            {paged.items.map((s) => (
              <li key={s.recipe.id}>
                <RecipeCard s={s} />
              </li>
            ))}
          </ul>
          <Pager
            page={paged.page}
            pages={paged.pages}
            total={shown?.length ?? 0}
            onPage={(p) => {
              put('page', p > 0 ? String(p + 1) : null, true)
              window.scrollTo({ top: 0 })
            }}
          />
        </>
      )}
      <ImportDialog open={importOpen} onClose={() => setImportOpen(false)} />
    </>
  )
}

function CategorySelect({ categories, value, onChange }: { categories: string[]; value: string | null; onChange: (c: string | null) => void }) {
  const { t } = useTranslation()
  if (categories.length === 0) return null
  return (
    <select
      aria-label={t('recipes.category')}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value || null)}
      className={cn('min-h-10 rounded-full px-4 text-sm font-medium ring-1', value ? 'bg-leaf-600 text-white ring-leaf-600' : 'bg-surface text-ink-700 ring-cream-200')}
      data-testid="recipe-category-filter"
    >
      <option value="">{t('recipes.allCategories')}</option>
      {categories.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  )
}

function Pager({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  const { t } = useTranslation()
  return (
    <nav className="mt-4 flex items-center justify-between gap-3 text-sm text-ink-500" aria-label={t('recipes.pages')} data-testid="recipe-pager">
      <Button disabled={page === 0} onClick={() => onPage(page - 1)} aria-label={t('recipes.prevPage')}>
        <ChevronLeft className="size-4" />
      </Button>
      <span>{t('recipes.pageOf', { page: page + 1, pages, count: total })}</span>
      <Button disabled={page >= pages - 1} onClick={() => onPage(page + 1)} aria-label={t('recipes.nextPage')}>
        <ChevronRight className="size-4" />
      </Button>
    </nav>
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
          {r.image_url ? (
            <img src={r.image_url} alt="" referrerPolicy="no-referrer" loading="lazy" className="size-16 shrink-0 rounded-2xl bg-cream-100 object-cover" />
          ) : (
            <div className="flex size-16 shrink-0 items-center justify-center rounded-2xl bg-cream-100 text-ink-300" aria-hidden>
              <BookOpen className="size-6" />
            </div>
          )}
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold">{r.title}</h2>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-sm text-ink-500">
              {mins > 0 && (
                <span className="inline-flex items-center gap-1">
                  <Clock className="size-3.5" /> {t('recipes.minutes', { n: mins })}
                </span>
              )}
              <span>{t('recipes.servings', { count: r.servings })}</span>
              {r.course && <Badge tone="info">{t(`recipes.course_${r.course}`)}</Badge>}
              {(r.categories ?? []).slice(0, 2).map((c) => (
                <Badge key={c}>{c}</Badge>
              ))}
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
