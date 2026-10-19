import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, ChefHat, Loader2, ShoppingCart } from 'lucide-react'
import { post } from '../../api/client'
import { keys } from '../../api/queries'
import type { Recipe, ShoppingItem } from '../../api/types'
import { Badge, Button, Card, EmptyState, Field, Input, Select } from '../ui'
import { useToast } from '../Toast'
import { errorKey } from './ChatPanel'

function Section({ title, items, tone, className }: { title: string; items: string[]; tone: 'good' | 'bad' | 'warn'; className: string }) {
  if (items.length === 0) return null
  return (
    <div>
      <h4 className={`mb-1 text-xs font-bold uppercase tracking-wide ${className}`}>{title}</h4>
      <div className="flex flex-wrap gap-1.5">
        {items.map((x, i) => (
          <Badge key={`${x}-${i}`} tone={tone}>
            {x}
          </Badge>
        ))}
      </div>
    </div>
  )
}

export function RecipeCard({ recipe }: { recipe: Recipe }) {
  const { t } = useTranslation()
  const toast = useToast()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [done, setDone] = useState<Set<string>>(new Set())
  const added = recipe.missing.every((n) => done.has(n))

  // Explicit user click only: the AI never writes; this uses the normal shopping API.
  const add = useMutation({
    mutationFn: async () => {
      // Per-item progress is kept, so a retry after a failure never duplicates earlier items.
      for (const name of recipe.missing) {
        if (done.has(name)) continue
        await post<ShoppingItem>('/shopping', { name, quantity: 1 })
        done.add(name)
        setDone(new Set(done))
      }
    },
    onSuccess: () => {
      toast.push(t('assistant.addedMissing', { count: recipe.missing.length }), 'success')
      void qc.invalidateQueries({ queryKey: keys.shopping })
      void qc.invalidateQueries({ queryKey: keys.suggestions })
      void qc.invalidateQueries({ queryKey: keys.dashboard })
    },
    onError: () => {
      void qc.invalidateQueries({ queryKey: keys.shopping })
      toast.push(t('assistant.addFailed'), 'error')
    },
  })

  return (
    <Card className="flex flex-col gap-3">
      <div>
        <h3 className="text-lg font-bold">{recipe.title}</h3>
        {recipe.description && <p className="text-sm text-ink-500">{recipe.description}</p>}
      </div>
      <Section title={t('assistant.have')} items={recipe.have} tone="good" className="text-leaf-700" />
      {recipe.missing.length > 0 ? (
        <Section title={t('assistant.missing')} items={recipe.missing} tone="bad" className="text-tomato-600" />
      ) : (
        <p className="text-sm text-leaf-700">{t('assistant.nothingMissing')}</p>
      )}
      <Section title={t('assistant.substitutions')} items={recipe.substitutions} tone="warn" className="text-honey-600" />
      {recipe.steps.length > 0 && (
        <div>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="flex min-h-11 items-center gap-1 text-sm font-semibold text-ink-700"
          >
            <ChevronDown className={`size-4 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
            {open ? t('assistant.hideSteps') : t('assistant.showSteps')}
          </button>
          {open && (
            <ol className="ml-5 list-decimal space-y-1 text-sm" aria-label={t('assistant.steps')}>
              {recipe.steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          )}
        </div>
      )}
      {recipe.missing.length > 0 && (
        <Button variant="primary" loading={add.isPending} disabled={added} onClick={() => add.mutate()}>
          {added ? <Check className="size-4" aria-hidden /> : <ShoppingCart className="size-4" aria-hidden />}
          {t('assistant.addMissing')}
        </Button>
      )}
    </Card>
  )
}

export default function RecipesPanel({ locale }: { locale: 'da' | 'en' }) {
  const { t } = useTranslation()
  const [prompt, setPrompt] = useState('')
  const [count, setCount] = useState(3)
  const gen = useMutation({
    mutationFn: () =>
      post<{ recipes: Recipe[] }>('/ai/recipes', { prompt: prompt.trim() || null, count, locale }, { timeoutMs: 240_000 }),
  })

  return (
    <div className="flex flex-col gap-4">
      <form
        className="flex flex-col gap-3 sm:flex-row sm:items-end"
        onSubmit={(e) => {
          e.preventDefault()
          if (!gen.isPending) gen.mutate()
        }}
      >
        <Field label={t('assistant.recipePrompt')} className="flex-1">
          {(id) => (
            <Input id={id} value={prompt} maxLength={500} placeholder={t('assistant.recipePlaceholder')} onChange={(e) => setPrompt(e.target.value)} />
          )}
        </Field>
        <Field label={t('assistant.recipeCount')}>
          {(id) => (
            <Select id={id} value={count} onChange={(e) => setCount(Number(e.target.value))}>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Button type="submit" variant="primary" disabled={gen.isPending}>
          <ChefHat className="size-4" aria-hidden /> {t('assistant.suggest')}
        </Button>
      </form>
      <p className="text-xs text-ink-500">{t('assistant.aiNote')}</p>

      {gen.isPending && (
        <Card role="status" className="flex items-center gap-3 text-sm text-ink-700">
          <Loader2 className="size-5 animate-spin text-leaf-600" aria-hidden />
          {t('assistant.suggesting')}
        </Card>
      )}
      {gen.isError && (
        <Card role="alert" className="flex flex-wrap items-center gap-3 bg-tomato-50 text-sm text-tomato-600">
          <span className="flex-1">{t(errorKey(gen.error))}</span>
          <Button size="sm" onClick={() => gen.mutate()}>
            {t('assistant.retry')}
          </Button>
        </Card>
      )}
      {gen.data && gen.data.recipes.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-2">
          {gen.data.recipes.map((r, i) => (
            <RecipeCard key={`${r.title}-${i}`} recipe={r} />
          ))}
        </div>
      )}
      {!gen.data && !gen.isPending && !gen.isError && (
        <EmptyState icon={<ChefHat className="size-8" />} title={t('assistant.noRecipes')} hint={t('assistant.noRecipesHint')} />
      )}
    </div>
  )
}
