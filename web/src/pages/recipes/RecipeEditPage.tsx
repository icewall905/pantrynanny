import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { post, get, api } from '../../api/client'
import type { ParsedLine, Recipe, RecipeDraft, RecipeInput } from '../../api/recipes'
import { Button, Card, ErrorState, Field, Input, ListSkeleton, PageHeader, Textarea } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { formatQty } from '../../lib/format'

interface Form {
  title: string
  description: string
  servings: string
  prep_min: string
  cook_min: string
  ingredients: string
  instructions: string
  tags: string
  source_url: string | null
  source_name: string | null
  image_url: string | null
}

const empty: Form = {
  title: '',
  description: '',
  servings: '4',
  prep_min: '',
  cook_min: '',
  ingredients: '',
  instructions: '',
  tags: '',
  source_url: null,
  source_name: null,
  image_url: null,
}

function fromRecipe(r: Recipe | RecipeDraft): Form {
  return {
    title: r.title,
    description: r.description ?? '',
    servings: String(r.servings ?? 4),
    prep_min: r.prep_min != null ? String(r.prep_min) : '',
    cook_min: r.cook_min != null ? String(r.cook_min) : '',
    ingredients: ('id' in r ? r.ingredients.map((i) => i.raw) : r.ingredients).join('\n'),
    instructions: r.instructions.join('\n\n'),
    tags: r.tags.join(', '),
    source_url: r.source_url,
    source_name: r.source_name,
    image_url: r.image_url,
  }
}

const int = (s: string) => (s.trim() === '' ? null : Math.max(0, Math.round(Number(s))))

function toInput(f: Form, existing?: Recipe): RecipeInput {
  // keep explicit product links for lines that did not change
  const links = new Map(existing?.ingredients.map((i) => [i.raw, i.product_id]) ?? [])
  return {
    title: f.title.trim(),
    description: f.description.trim() || null,
    servings: Math.min(100, Math.max(1, int(f.servings) ?? 4)),
    prep_min: int(f.prep_min),
    cook_min: int(f.cook_min),
    ingredients: f.ingredients
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 100)
      .map((raw) => ({ raw, product_id: links.get(raw) ?? null })),
    instructions: f.instructions
      .split(/\n\s*\n|\n(?=\d+[.)]\s)/)
      .map((s) => s.replace(/^\d+[.)]\s*/, '').trim())
      .filter(Boolean),
    tags: f.tags
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
    source_url: f.source_url,
    source_name: f.source_name,
    image_url: f.image_url,
  }
}

export default function RecipeEditPage() {
  const { id } = useParams()
  const loc = useLocation()
  const draft = (loc.state as { draft?: RecipeDraft } | null)?.draft
  const { t } = useTranslation()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const existing = useQuery({ queryKey: ['recipe', id], queryFn: () => get<Recipe>(`/recipes/${id}`), enabled: !!id })
  const [edited, setF] = useState<Form | null>(() => (id ? null : draft ? fromRecipe(draft) : empty))
  // an existing recipe fills the form once it has loaded; edits live in `edited`
  const f = edited ?? (existing.data ? fromRecipe(existing.data) : null)
  const [preview, setPreview] = useState<ParsedLine[]>([])
  const lines = f?.ingredients ?? ''
  useEffect(() => {
    const ls = lines.split('\n').filter((s) => s.trim()).slice(0, 100)
    if (!ls.length) return
    const tm = setTimeout(() => {
      post<ParsedLine[]>('/recipes/parse', { lines: ls })
        .then(setPreview)
        .catch(() => undefined)
    }, 400)
    return () => clearTimeout(tm)
  }, [lines])

  const save = useMutation({
    mutationFn: (body: RecipeInput) =>
      id
        ? api<Recipe>(`/recipes/${id}`, { method: 'PUT', body: body as never, headers: { 'If-Match': String(existing.data!.version) } })
        : post<Recipe>('/recipes', body as never),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['recipes'] })
      qc.setQueryData(['recipe', r.id], r)
      toast.push(t('common.saved'), 'success')
      nav(`/recipes/${r.id}`, { replace: true })
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })

  if (id && existing.isError) return <ErrorState error={existing.error} onRetry={() => void existing.refetch()} />
  if (!f) return <ListSkeleton rows={6} />
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF({ ...f, [k]: v })

  return (
    <>
      <PageHeader title={id ? t('recipes.edit') : t('recipes.new')} subtitle={draft ? t('recipes.fromImport', { site: draft.source_name ?? new URL(draft.source_url).hostname }) : undefined} />
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (f.title.trim()) save.mutate(toInput(f, existing.data))
        }}
      >
        <Card className="space-y-4">
          <Field label={t('recipes.fTitle')}>{(i) => <Input id={i} required maxLength={200} value={f.title} onChange={(e) => set('title', e.target.value)} />}</Field>
          <Field label={t('recipes.fDescription')}>{(i) => <Textarea id={i} rows={2} maxLength={2000} value={f.description} onChange={(e) => set('description', e.target.value)} />}</Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label={t('recipes.fServings')}>{(i) => <Input id={i} inputMode="numeric" value={f.servings} onChange={(e) => set('servings', e.target.value)} />}</Field>
            <Field label={t('recipes.fPrep')}>{(i) => <Input id={i} inputMode="numeric" value={f.prep_min} onChange={(e) => set('prep_min', e.target.value)} />}</Field>
            <Field label={t('recipes.fCook')}>{(i) => <Input id={i} inputMode="numeric" value={f.cook_min} onChange={(e) => set('cook_min', e.target.value)} />}</Field>
          </div>
        </Card>
        <Card className="grid gap-4 lg:grid-cols-2">
          <Field label={t('recipes.fIngredients')} hint={t('recipes.fIngredientsHint')}>
            {(i) => <Textarea id={i} rows={12} value={f.ingredients} onChange={(e) => set('ingredients', e.target.value)} placeholder={'3 æg\n5 dl mælk\n250 g hvedemel\n1 knivspids salt'} />}
          </Field>
          <div>
            <div className="mb-1 text-sm font-medium text-ink-700">{t('recipes.understood')}</div>
            <ul className="divide-y divide-cream-200 rounded-xl bg-cream-50 px-3 text-sm ring-1 ring-cream-200" data-testid="parse-preview">
              {(f.ingredients.trim() ? preview : []).map((p, n) => (
                <li key={n} className="flex gap-2 py-1.5">
                  <span className="w-20 shrink-0 tabular-nums text-ink-500">
                    {p.quantity != null ? formatQty(p.quantity) : '–'} {p.unit ?? ''}
                  </span>
                  <span className="min-w-0 flex-1 font-medium">{p.name}</span>
                  {p.optional && <span className="text-ink-500">{t('recipes.optional')}</span>}
                </li>
              ))}
            </ul>
          </div>
        </Card>
        <Card className="space-y-4">
          <Field label={t('recipes.fMethod')} hint={t('recipes.fMethodHint')}>
            {(i) => <Textarea id={i} rows={10} value={f.instructions} onChange={(e) => set('instructions', e.target.value)} />}
          </Field>
          <Field label={t('recipes.fTags')}>{(i) => <Input id={i} value={f.tags} onChange={(e) => set('tags', e.target.value)} placeholder={t('recipes.fTagsPh')} />}</Field>
        </Card>
        <div className="flex gap-2">
          <Button type="submit" variant="primary" loading={save.isPending} disabled={!f.title.trim()} data-testid="recipe-save">
            {t('common.save')}
          </Button>
          <Button type="button" onClick={() => nav(-1)}>
            {t('common.cancel')}
          </Button>
        </div>
      </form>
    </>
  )
}
