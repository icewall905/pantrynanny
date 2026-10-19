import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Check, ChevronLeft, ChevronRight, Plus, ShoppingBasket, Trash2 } from 'lucide-react'
import { del, get, patch, post } from '../api/client'
import type { Meal, RecipeSummary, Slot } from '../api/recipes'
import { Badge, Button, ErrorState, Field, Input, ListSkeleton, Modal, PageHeader, Select } from '../components/ui'
import { useToast } from '../components/Toast'
import { cn, todayISO } from '../lib/format'

const SLOTS: Slot[] = ['breakfast', 'lunch', 'dinner', 'snack']

function monday(d: Date) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7))
  return x
}
const iso = (d: Date) => todayISO(d)
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)

export default function MealPlanPage() {
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const toast = useToast()
  const [start, setStart] = useState(() => monday(new Date()))
  const [adding, setAdding] = useState<string | null>(null)
  const startIso = iso(start)
  const plan = useQuery({ queryKey: ['meal-plan', startIso], queryFn: () => get<Meal[]>(`/meal-plan?start=${startIso}&days=7`) })
  const refresh = () => void qc.invalidateQueries({ queryKey: ['meal-plan'] })
  const toggle = useMutation({ mutationFn: (m: Meal) => patch(`/meal-plan/${m.id}`, { cooked: !m.cooked_at }), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (m: Meal) => del(`/meal-plan/${m.id}`), onSuccess: refresh })
  const shop = useMutation({
    mutationFn: () => post<{ added: string[] }>('/meal-plan/shopping', { start: startIso, days: 7 }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['shopping'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
      toast.push(r.added.length ? t('plan.shopped', { count: r.added.length, names: r.added.slice(0, 4).join(', ') }) : t('plan.nothingToBuy'), 'success')
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i))
  const today = todayISO()

  return (
    <>
      <PageHeader
        title={t('plan.title')}
        subtitle={t('plan.subtitle')}
        actions={
          <Button onClick={() => shop.mutate()} loading={shop.isPending} disabled={!plan.data?.some((m) => m.recipe_id && !m.cooked_at)} data-testid="plan-shop">
            <ShoppingBasket className="size-4" /> {t('plan.shopWeek')}
          </Button>
        }
      />
      <div className="mb-4 flex items-center gap-2">
        <Button size="sm" variant="ghost" aria-label={t('plan.prev')} onClick={() => setStart(addDays(start, -7))}>
          <ChevronLeft className="size-5" />
        </Button>
        <div className="min-w-0 flex-1 text-center font-semibold">
          {start.toLocaleDateString(i18n.language, { day: 'numeric', month: 'short' })} – {addDays(start, 6).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short' })}
        </div>
        <Button size="sm" variant="ghost" aria-label={t('plan.next')} onClick={() => setStart(addDays(start, 7))}>
          <ChevronRight className="size-5" />
        </Button>
      </div>
      {plan.isError ? (
        <ErrorState error={plan.error} onRetry={() => void plan.refetch()} />
      ) : !plan.data ? (
        <ListSkeleton rows={7} />
      ) : (
        <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="plan-week">
          {days.map((d) => {
            const key = iso(d)
            const meals = plan.data.filter((m) => m.day === key).sort((a, b) => SLOTS.indexOf(a.slot) - SLOTS.indexOf(b.slot))
            return (
              <li key={key} className={cn('rounded-3xl bg-surface p-4 ring-1 ring-cream-200', key === today && 'ring-2 ring-leaf-500/60')}>
                <div className="mb-2 flex items-center justify-between">
                  <h2 className="font-semibold">{cap(d.toLocaleDateString(i18n.language, { weekday: 'long', day: 'numeric', month: 'short' }))}</h2>
                  <Button size="sm" variant="ghost" aria-label={t('plan.add')} onClick={() => setAdding(key)}>
                    <Plus className="size-4" />
                  </Button>
                </div>
                {meals.length === 0 ? (
                  <p className="text-sm text-ink-500">{t('plan.empty')}</p>
                ) : (
                  <ul className="space-y-1.5">
                    {meals.map((m) => (
                      <li key={m.id} className="flex items-center gap-2 rounded-2xl bg-cream-50 px-3 py-2 ring-1 ring-cream-200">
                        <button
                          type="button"
                          aria-label={m.cooked_at ? t('plan.markNotCooked') : t('plan.markCooked')}
                          onClick={() => toggle.mutate(m)}
                          className={cn('grid size-7 shrink-0 place-items-center rounded-full ring-1', m.cooked_at ? 'bg-leaf-600 text-white ring-leaf-600' : 'ring-cream-200')}
                        >
                          {m.cooked_at && <Check className="size-4" />}
                        </button>
                        <div className="min-w-0 flex-1">
                          <div className="text-xs uppercase tracking-wide text-ink-500">{t(`plan.slot_${m.slot}`)}</div>
                          {m.recipe_id ? (
                            <Link to={`/recipes/${m.recipe_id}?entry=${m.id}${m.servings ? `&servings=${m.servings}` : ''}`} className={cn('block truncate font-medium hover:underline', m.cooked_at && 'line-through opacity-60')}>
                              {m.recipe_title}
                            </Link>
                          ) : (
                            <div className={cn('truncate font-medium', m.cooked_at && 'line-through opacity-60')}>{m.title}</div>
                          )}
                        </div>
                        {m.missing != null && !m.cooked_at && (
                          <Badge tone={m.missing ? 'warn' : 'good'}>{m.missing ? t('recipes.missingN', { count: m.missing }) : t('recipes.ready')}</Badge>
                        )}
                        <button type="button" aria-label={t('common.delete')} onClick={() => remove.mutate(m)} className="grid size-8 place-items-center rounded-xl text-ink-500 hover:bg-cream-200/70">
                          <Trash2 className="size-4" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ol>
      )}
      <p className="mt-4 text-xs text-ink-500">{t('plan.noDeduction')}</p>
      {adding && <AddMeal day={adding} onClose={() => setAdding(null)} onSaved={refresh} />}
    </>
  )
}

function AddMeal({ day, onClose, onSaved }: { day: string; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const recipes = useQuery({ queryKey: ['recipes', 'suggest', null], queryFn: () => get<RecipeSummary[]>('/recipes/suggest') })
  const [recipeId, setRecipeId] = useState('')
  const [title, setTitle] = useState('')
  const [slot, setSlot] = useState<Slot>('dinner')
  const [servings, setServings] = useState('')
  const save = useMutation({
    mutationFn: () =>
      post('/meal-plan', {
        day,
        slot,
        recipe_id: recipeId || null,
        title: recipeId ? null : title.trim(),
        servings: servings ? Number(servings) : null,
      }),
    onSuccess: () => {
      onSaved()
      onClose()
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  return (
    <Modal
      open
      onClose={onClose}
      title={t('plan.addTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={save.isPending} disabled={!recipeId && !title.trim()} onClick={() => save.mutate()} data-testid="plan-save">
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label={t('plan.recipe')} hint={t('plan.recipeHint')}>
          {(id) => (
            <Select id={id} value={recipeId} onChange={(e) => setRecipeId(e.target.value)}>
              <option value="">{t('plan.noRecipe')}</option>
              {(recipes.data ?? []).map((s) => (
                <option key={s.recipe.id} value={s.recipe.id}>
                  {s.recipe.title}
                  {s.availability.missing ? ` (${t('recipes.missingN', { count: s.availability.missing })})` : ` ✓`}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {!recipeId && <Field label={t('plan.freeText')}>{(id) => <Input id={id} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder={t('plan.freeTextPh')} />}</Field>}
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('plan.slot')}>
            {(id) => (
              <Select id={id} value={slot} onChange={(e) => setSlot(e.target.value as Slot)}>
                {SLOTS.map((s) => (
                  <option key={s} value={s}>
                    {t(`plan.slot_${s}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t('recipes.fServings')}>{(id) => <Input id={id} inputMode="numeric" value={servings} onChange={(e) => setServings(e.target.value)} placeholder="–" />}</Field>
        </div>
      </div>
    </Modal>
  )
}
