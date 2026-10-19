import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { CalendarPlus, ChefHat, Clock, ExternalLink, Minus, Pencil, Plus, ShoppingBasket, Trash2 } from 'lucide-react'
import { del, get, patch, post } from '../../api/client'
import { totalMinutes, type Availability, type IngredientAvailability, type Recipe, type Slot } from '../../api/recipes'
import { useInvalidateStock } from '../../api/queries'
import { Badge, Button, Card, ErrorState, Field, Input, ListSkeleton, Modal, Select } from '../../components/ui'
import { useToast } from '../../components/Toast'
import { enqueueOp } from '../../offline'
import { cn, formatQty, todayISO } from '../../lib/format'

const TONE = { have: 'good', low: 'warn', missing: 'bad', staple: 'neutral', optional: 'neutral' } as const

export default function RecipeDetailPage() {
  const { id = '' } = useParams()
  const [params] = useSearchParams()
  const entryId = params.get('entry')
  const { t } = useTranslation()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [servings, setServings] = useState<number | null>(() => Number(params.get('servings')) || null)
  const [cookOpen, setCookOpen] = useState(false)
  const [planOpen, setPlanOpen] = useState(false)
  const recipe = useQuery({ queryKey: ['recipe', id], queryFn: () => get<Recipe>(`/recipes/${id}`) })
  const sv = servings ?? recipe.data?.servings ?? null
  const avail = useQuery({
    queryKey: ['recipe', id, 'availability', sv],
    queryFn: () => get<Availability>(`/recipes/${id}/availability${sv ? `?servings=${sv}` : ''}`),
    enabled: !!recipe.data,
  })
  const shop = useMutation({
    mutationFn: () => post<{ added: string[] }>(`/recipes/${id}/shopping`, { servings: sv }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['shopping'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
      toast.push(r.added.length ? t('recipes.addedToShopping', { count: r.added.length }) : t('recipes.nothingToBuy'), 'success')
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  const remove = useMutation({
    mutationFn: () => del(`/recipes/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['recipes'] })
      nav('/recipes')
    },
  })

  if (recipe.isError) return <ErrorState error={recipe.error} onRetry={() => void recipe.refetch()} />
  if (!recipe.data) return <ListSkeleton rows={5} />
  const r = recipe.data
  const a = avail.data
  const mins = totalMinutes(r)
  const missing = a?.items.filter((i) => i.status === 'missing' || i.status === 'low').length ?? 0

  return (
    <div className="space-y-4">
      <div>
        <Link to="/recipes" className="text-sm text-ink-500 hover:underline">
          ← {t('recipes.title')}
        </Link>
        <div className="mt-2 flex flex-wrap items-start gap-4">
          {r.image_url && (
            <img src={r.image_url} alt="" referrerPolicy="no-referrer" loading="lazy" className="size-28 rounded-3xl bg-cream-100 object-cover" />
          )}
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold tracking-[-0.025em] sm:text-[2rem]">{r.title}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-500">
              {mins > 0 && (
                <span className="inline-flex items-center gap-1">
                  <Clock className="size-4" /> {t('recipes.minutes', { n: mins })}
                </span>
              )}
              {r.source_url && (
                <a href={r.source_url} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1 hover:underline">
                  <ExternalLink className="size-4" /> {r.source_name || new URL(r.source_url).hostname}
                </a>
              )}
              {r.tags.map((tag) => (
                <Badge key={tag}>{tag}</Badge>
              ))}
            </div>
            {r.description && <p className="mt-2 text-ink-700">{r.description}</p>}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => setCookOpen(true)} disabled={!a} data-testid="cook-open">
          <ChefHat className="size-4" /> {t('recipes.cook')}
        </Button>
        <Button onClick={() => shop.mutate()} loading={shop.isPending} disabled={!a || missing === 0}>
          <ShoppingBasket className="size-4" /> {t('recipes.shopMissing', { count: missing })}
        </Button>
        <Button onClick={() => setPlanOpen(true)}>
          <CalendarPlus className="size-4" /> {t('recipes.plan')}
        </Button>
        <Link to={`/recipes/${id}/edit`} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-surface px-4 text-sm font-semibold ring-1 ring-cream-200 hover:bg-cream-200/70">
          <Pencil className="size-4" /> {t('common.edit')}
        </Link>
        <Button variant="ghost" onClick={() => window.confirm(t('recipes.confirmDelete')) && remove.mutate()}>
          <Trash2 className="size-4" /> {t('common.delete')}
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Card>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">{t('recipes.ingredients')}</h2>
            <div className="flex items-center gap-1" aria-label={t('recipes.servingsLabel')}>
              <Button size="sm" variant="ghost" aria-label="−" onClick={() => sv && sv > 1 && setServings(sv - 1)}>
                <Minus className="size-4" />
              </Button>
              <span className="min-w-20 text-center text-sm font-semibold tabular-nums" data-testid="servings">
                {t('recipes.servings', { count: sv ?? r.servings })}
              </span>
              <Button size="sm" variant="ghost" aria-label="+" onClick={() => sv && setServings(sv + 1)}>
                <Plus className="size-4" />
              </Button>
            </div>
          </div>
          {a && (
            <p className="mb-2 text-sm text-ink-500">
              {a.missing === 0 ? t('recipes.allHome') : t('recipes.coverage', { have: a.have, of: a.required })}
            </p>
          )}
          <ul className="divide-y divide-cream-200" data-testid="ingredients">
            {(a?.items ?? r.ingredients.map((ingredient) => ({ ingredient }) as IngredientAvailability)).map((it) => (
              <li key={it.ingredient.id} className="flex items-start gap-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{scaledLine(it, r.servings, sv ?? r.servings)}</div>
                  {it.product && (
                    <div className="text-xs text-ink-500">
                      {it.product.name} · {t('recipes.inStock', { qty: formatQty(it.product.total_quantity), unit: t(`units.${it.product.stock_unit}`) })}
                      {it.expiring && <span className="ml-1 text-honey-600">· {t('recipes.expiringSoon')}</span>}
                    </div>
                  )}
                </div>
                {it.status && <Badge tone={TONE[it.status]}>{t(`recipes.status_${it.status}`)}</Badge>}
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <h2 className="mb-2 text-lg font-semibold">{t('recipes.method')}</h2>
          {r.instructions.length === 0 ? (
            <p className="text-sm text-ink-500">{t('recipes.noMethod')}</p>
          ) : (
            <ol className="space-y-3">
              {r.instructions.map((s, i) => (
                <li key={i} className="flex gap-3">
                  <span className="grid size-7 shrink-0 place-items-center rounded-full bg-leaf-100 text-sm font-bold text-leaf-700">{i + 1}</span>
                  <p className="pt-0.5 leading-relaxed">{s}</p>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>

      {a && cookOpen && (
        <CookDialog
          recipe={r}
          availability={a}
          entryId={entryId}
          onClose={() => setCookOpen(false)}
          onDone={() => {
            void qc.invalidateQueries({ queryKey: ['recipe', id] })
            void qc.invalidateQueries({ queryKey: ['meal-plan'] })
          }}
        />
      )}
      <PlanDialog open={planOpen} onClose={() => setPlanOpen(false)} recipe={r} servings={sv ?? r.servings} />
    </div>
  )
}

function scaledLine(it: IngredientAvailability, base: number, servings: number) {
  const g = it.ingredient
  if (g.quantity == null || base === servings) return g.raw
  const q = Math.round(((g.quantity * servings) / base) * 100) / 100
  return [formatQty(q), g.unit && g.unit !== 'pcs' ? g.unit : null, g.name, g.note ? `(${g.note})` : null].filter(Boolean).join(' ')
}

interface Line {
  key: string
  name: string
  productId: string
  unit: string
  stock: number
  qty: string
  on: boolean
}

/** Shows exactly what will be taken out of stock; nothing happens until the user confirms. */
function CookDialog({
  recipe,
  availability,
  entryId,
  onClose,
  onDone,
}: {
  recipe: Recipe
  availability: Availability
  entryId: string | null
  onClose: () => void
  onDone: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const invalidate = useInvalidateStock()
  const initial = useMemo<Line[]>(
    () =>
      availability.items
        .filter((it) => it.product && it.product.total_quantity > 0 && it.status !== 'staple')
        .map((it) => {
          const p = it.product!
          const need = it.need != null ? Math.min(it.need, p.total_quantity) : null
          return {
            key: it.ingredient.id,
            name: p.name,
            productId: p.id,
            unit: p.stock_unit,
            stock: p.total_quantity,
            qty: need != null ? String(need) : '',
            on: need != null && need > 0,
          }
        }),
    [availability],
  )
  const [lines, setLines] = useState(initial)
  const [busy, setBusy] = useState(false)
  const set = (k: string, v: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === k ? { ...l, ...v } : l)))
  const chosen = lines.filter((l) => l.on && Number(l.qty.replace(',', '.')) > 0)

  const confirm = async () => {
    setBusy(true)
    const ops: { id: string; productId: string; qty: number }[] = []
    try {
      for (const l of chosen) {
        const qty = Math.min(l.stock, Math.round(Number(l.qty.replace(',', '.')) * 1000) / 1000)
        const op = await enqueueOp({ type: 'remove', product_id: l.productId, quantity: qty, reason: 'recipe' })
        ops.push({ id: op.client_op_id, productId: l.productId, qty })
      }
      if (entryId) await patch(`/meal-plan/${entryId}`, { cooked: true }).catch(() => undefined)
      void invalidate()
      onDone()
      onClose()
      toast.push(t('recipes.cooked', { title: recipe.title, count: ops.length }), 'success', {
        label: t('kitchen.undo'),
        onClick: async () => {
          for (const o of ops) await enqueueOp({ type: 'undo', undoes_client_op_id: o.id, product_id: o.productId, quantity: o.qty })
          if (entryId) await patch(`/meal-plan/${entryId}`, { cooked: false }).catch(() => undefined)
          void invalidate()
          onDone()
          toast.push(t('recipes.cookUndone'), 'info')
        },
      })
    } catch {
      toast.push(t('inventory.changeFailed'), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={t('recipes.cookTitle', { title: recipe.title })}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={busy} onClick={() => void confirm()} data-testid="cook-confirm">
            {chosen.length ? t('recipes.cookConfirm', { count: chosen.length }) : t('recipes.cookNothing')}
          </Button>
        </>
      }
    >
      <p className="mb-3 text-sm text-ink-500">{t('recipes.cookHint')}</p>
      {lines.length === 0 ? (
        <p className="py-2 text-sm">{t('recipes.cookNoneInStock')}</p>
      ) : (
        <ul className="divide-y divide-cream-200" data-testid="cook-lines">
          {lines.map((l) => (
            <li key={l.key} className="flex items-center gap-3 py-2">
              <input type="checkbox" className="size-5 accent-leaf-600" checked={l.on} onChange={(e) => set(l.key, { on: e.target.checked })} aria-label={l.name} />
              <span className={cn('min-w-0 flex-1 truncate', !l.on && 'text-ink-500')}>{l.name}</span>
              <Input
                className="w-20! text-right"
                inputMode="decimal"
                value={l.qty}
                placeholder="?"
                aria-label={t('recipes.amountFor', { name: l.name })}
                onChange={(e) => set(l.key, { qty: e.target.value, on: e.target.value !== '' })}
              />
              <span className="w-10 text-sm text-ink-500">{t(`units.${l.unit}`)}</span>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}

function PlanDialog({ open, onClose, recipe, servings }: { open: boolean; onClose: () => void; recipe: Recipe; servings: number }) {
  const { t } = useTranslation()
  const toast = useToast()
  const qc = useQueryClient()
  const [day, setDay] = useState(() => todayISO())
  const [slot, setSlot] = useState<Slot>('dinner')
  const save = useMutation({
    mutationFn: () => post('/meal-plan', { day, slot, recipe_id: recipe.id, servings }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['meal-plan'] })
      toast.push(t('recipes.planned'), 'success')
      onClose()
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('recipes.planTitle')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t('plan.day')}>{(id) => <Input id={id} type="date" value={day} onChange={(e) => setDay(e.target.value)} />}</Field>
        <Field label={t('plan.slot')}>
          {(id) => (
            <Select id={id} value={slot} onChange={(e) => setSlot(e.target.value as Slot)}>
              {(['breakfast', 'lunch', 'dinner', 'snack'] as const).map((s) => (
                <option key={s} value={s}>
                  {t(`plan.slot_${s}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      <p className="mt-3 text-xs text-ink-500">{t('plan.noDeduction')}</p>
    </Modal>
  )
}
