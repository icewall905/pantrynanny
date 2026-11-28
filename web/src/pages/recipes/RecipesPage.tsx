import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { BookOpen, ChevronLeft, ChevronRight, Clock, Download, Link2, Plus, Puzzle, Sparkles } from 'lucide-react'
import { get, post, qs } from '../../api/client'
import { COURSES, totalMinutes, type Course, type RecipeDraft, type RecipeSummary } from '../../api/recipes'
import { Badge, Button, Chip, EmptyState, ErrorState, Field, Input, ListSkeleton, Modal, PageHeader, Tabs } from '../../components/ui'
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
  // ?import=<url> comes from the browser extension / bookmarklet: read that recipe right away
  const [importUrl] = useState(() => sp.get('import'))
  const [importOpen, setImportOpen] = useState(() => !!importUrl)
  const [extOpen, setExtOpen] = useState(false)
  useEffect(() => {
    if (importUrl) put('import', null, true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const suggest = useQuery({
    queryKey: ['recipes', 'suggest', maxMin, course],
    queryFn: () => get<RecipeSummary[]>(`/recipes/suggest${qs({ show_all: true, max_minutes: maxMin, course })}`),
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
            <Button onClick={() => setExtOpen(true)} data-testid="recipe-extension">
              <Puzzle className="size-4" /> {t('recipes.extension')}
            </Button>
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
          <ul className="grid grid-cols-1 gap-4 min-[480px]:grid-cols-2 lg:grid-cols-3" data-testid="recipe-list">
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
      <ImportDialog open={importOpen} initialUrl={importUrl} onClose={() => setImportOpen(false)} />
      <ExtensionDialog open={extOpen} onClose={() => setExtOpen(false)} />
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
  const chips = [...(r.course ? [t(`recipes.course_${r.course}`)] : []), ...(r.categories ?? []), ...r.tags].filter((c, i, all) => all.indexOf(c) === i).slice(0, 3)
  return (
    <Link
      to={`/recipes/${r.id}`}
      className="group flex h-full flex-col overflow-hidden rounded-[var(--radius-card)] bg-surface shadow-card ring-1 ring-cream-200/70 transition hover:-translate-y-0.5 hover:shadow-lg focus-visible:ring-2 focus-visible:ring-leaf-500"
      data-testid="recipe-card"
    >
      <div className="relative aspect-[16/10] bg-cream-100">
        {r.image_url ? (
          <img src={r.image_url} alt="" referrerPolicy="no-referrer" loading="lazy" className="size-full object-cover" />
        ) : (
          <div className="flex size-full items-center justify-center text-ink-300" aria-hidden>
            <BookOpen className="size-10" />
          </div>
        )}
        {r.description && (
          <div className="absolute inset-0 flex items-center bg-leaf-800/80 p-4 text-sm leading-snug text-white opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" aria-hidden>
            <p className="line-clamp-5">{r.description}</p>
          </div>
        )}
        {a.required > 0 && (
          <div className="absolute inset-x-0 bottom-0 h-1 bg-black/20" aria-hidden>
            <div className={cn('h-full', ready ? 'bg-leaf-500' : 'bg-honey-400')} style={{ width: `${Math.round(a.coverage * 100)}%` }} />
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3.5">
        <h2 className="line-clamp-2 text-base font-semibold leading-snug">{r.title}</h2>
        {chips.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {chips.map((c) => (
              <span key={c} className="rounded-md bg-leaf-600 px-2 py-0.5 text-xs font-medium text-white">
                {c}
              </span>
            ))}
          </div>
        )}
        {a.uses_expiring.length > 0 && (
          <p className="flex items-center gap-1.5 text-xs text-honey-600">
            <Sparkles className="size-3.5 shrink-0" /> <span className="line-clamp-1">{t('recipes.usesExpiring', { names: a.uses_expiring.join(', ') })}</span>
          </p>
        )}
        <div className="mt-auto flex items-center gap-3 pt-1 text-xs text-ink-500">
          {mins > 0 && (
            <span className="inline-flex items-center gap-1">
              <Clock className="size-3.5" /> {t('recipes.minutes', { n: mins })}
            </span>
          )}
          {a.required > 0 && <span title={t('recipes.coverage', { have: a.have, of: a.required })}>{a.have}/{a.required}</span>}
          <Badge className="ml-auto" tone={ready && a.required > 0 ? 'good' : a.coverage >= 0.6 ? 'warn' : 'neutral'}>
            {a.required === 0 ? t('recipes.nothingToCheck') : ready ? (a.swaps ? t('recipes.readySwaps', { count: a.swaps }) : t('recipes.ready')) : t('recipes.missingN', { count: a.missing })}
          </Badge>
        </div>
      </div>
    </Link>
  )
}

function ImportDialog({ open, initialUrl, onClose }: { open: boolean; initialUrl?: string | null; onClose: () => void }) {
  const { t } = useTranslation()
  const nav = useNavigate()
  const toast = useToast()
  const [url, setUrl] = useState(initialUrl ?? '')
  const run = useMutation({
    mutationFn: (u: string) => post<RecipeDraft>('/recipes/import', { url: u.trim() }),
    onSuccess: (draft) => {
      onClose()
      nav('/recipes/new', { state: { draft } })
    },
    onError: (e) => toast.push(e instanceof ApiError ? e.message : t('recipes.importFailed'), 'error'),
  })
  const started = useRef(false)
  useEffect(() => {
    // sent by the extension: read it at once (the dialog stays open to retry or edit on error)
    if (!started.current && initialUrl && /^https?:\/\/.+/.test(initialUrl)) {
      started.current = true
      run.mutate(initialUrl)
    }
  }, [initialUrl, run])
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('recipes.importTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={run.isPending} disabled={!/^https?:\/\/.+/.test(url.trim())} onClick={() => run.mutate(url)}>
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

function ExtensionDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  // Bookmarklet: works in any browser (also phones) without installing anything.
  const bookmarklet = `javascript:void(window.open(${JSON.stringify(`${window.location.origin}/recipes?import=`)}+encodeURIComponent(location.href)))`
  const ref = useRef<HTMLAnchorElement>(null)
  useEffect(() => {
    // React blocks javascript: URLs in href, so set it on the element directly
    if (open) ref.current?.setAttribute('href', bookmarklet)
  }, [open, bookmarklet])
  return (
    <Modal open={open} onClose={onClose} title={t('recipes.extTitle')} footer={<Button onClick={onClose}>{t('common.close')}</Button>}>
      <div className="space-y-4 text-sm text-ink-700">
        <p>{t('recipes.extIntro')}</p>
        <a
          href="/downloads/pantrynanny-recipe-import.zip"
          download
          className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-leaf-600 px-4 font-semibold text-white hover:bg-leaf-800"
          data-testid="recipe-extension-download"
        >
          <Download className="size-4" /> {t('recipes.extDownload')}
        </a>
        <ol className="list-decimal space-y-1 pl-5">
          <li>{t('recipes.extChrome')}</li>
          <li>{t('recipes.extFirefox')}</li>
          <li>{t('recipes.extServer', { origin: window.location.origin })}</li>
        </ol>
        <div>
          <p className="font-semibold">{t('recipes.extBookmarklet')}</p>
          <p className="mb-2 text-ink-500">{t('recipes.extBookmarkletHint')}</p>
          <a ref={ref} onClick={(e) => e.preventDefault()} className="inline-flex items-center gap-2 rounded-xl bg-cream-100 px-3 py-2 font-semibold ring-1 ring-cream-200">
            <Link2 className="size-4" /> {t('recipes.extBookmarkletName')}
          </a>
        </div>
      </div>
    </Modal>
  )
}
