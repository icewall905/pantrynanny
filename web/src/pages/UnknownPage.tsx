import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Camera, CheckCircle2, SkipForward, Sparkles } from 'lucide-react'
import { ApiError, get, patch, post } from '../api/client'
import { useAiStatus, useCategories, useLocations } from '../api/queries'
import { UNITS, type AiIdentifySuggestion, type Product, type Unit } from '../api/types'
import { ProductThumb } from '../components/ProductThumb'
import { conflictProduct } from '../components/ProductForm'
import { useToast } from '../components/Toast'
import { Button, Card, Chip, EmptyState, ErrorState, Field, Input, ListSkeleton, PageHeader, Select } from '../components/ui'

async function fetchUnknown(): Promise<Product[]> {
  const [a, b] = await Promise.all([
    get<Product[]>('/products?status=unknown&limit=100'),
    get<Product[]>('/products?status=needs_review&limit=100'),
  ])
  return [...a, ...b]
}

function Editor({ product, onSkip, remaining }: { product: Product; onSkip: () => void; remaining: number }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const toast = useToast()
  const cats = useCategories()
  const locs = useLocations()
  const ai = useAiStatus()
  const fileRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState(product.name)
  const [brand, setBrand] = useState(product.brand ?? '')
  const [category, setCategory] = useState(product.category_id ?? '')
  const [size, setSize] = useState(product.package_size != null ? String(product.package_size) : '')
  const [unit, setUnit] = useState<string>(product.package_unit ?? '')
  const [location, setLocation] = useState(product.default_location_id ?? '')
  const [version, setVersion] = useState(product.version)
  const [image, setImage] = useState(product.image_url)
  const [lastFile, setLastFile] = useState<File | null>(null)

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return post<Product>(`/products/${product.id}/photo`, fd)
    },
    onSuccess: (p) => {
      if (p?.image_url) setImage(p.image_url)
      void qc.invalidateQueries({ queryKey: ['unknown'] })
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })

  const identify = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return post<AiIdentifySuggestion>('/ai/identify-photo', fd)
    },
    onSuccess: (s) => {
      if (s.name) setName(s.name)
      if (s.brand) setBrand(s.brand)
      if (s.package_size != null) setSize(String(s.package_size))
      if (s.package_unit) setUnit(s.package_unit)
      const guess = cats.data?.find((c) => c.name.toLowerCase() === s.category_guess?.toLowerCase())
      if (guess) setCategory(guess.id)
      toast.push(t('unknown.suggested'), 'info')
    },
    onError: () => toast.push(t('unknown.aiFailed'), 'error'),
  })

  const save = useMutation({
    mutationFn: () =>
      patch<Product>(
        `/products/${product.id}`,
        {
          name: name.trim(),
          brand: brand.trim() || null,
          category_id: category || null,
          package_size: size.trim() ? Number(size.replace(',', '.')) : null,
          package_unit: unit || null,
          default_location_id: location || null,
          status: 'known',
        },
        { headers: { 'If-Match': String(version) } },
      ),
    onSuccess: () => {
      toast.push(t('unknown.saved'), 'success')
      void qc.invalidateQueries({ queryKey: ['unknown'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
      void qc.invalidateQueries({ queryKey: ['inventory'] })
    },
    onError: (e) => {
      const c = conflictProduct(e)
      if (c) setVersion(c.version)
      toast.push(e instanceof ApiError && e.status === 409 ? t('product.conflictTitle') : t('common.saveFailed'), 'error')
    },
  })

  const onFile = (f?: File) => {
    if (!f) return
    setLastFile(f)
    upload.mutate(f)
  }
  const canAi = ai.data?.enabled && ai.data.reachable

  return (
    <Card className="space-y-5">
      <div className="flex items-center gap-4">
        <ProductThumb name={name || '?'} src={image} className="size-24 text-3xl" />
        <div className="flex flex-col gap-2">
          <Button onClick={() => fileRef.current?.click()} loading={upload.isPending}>
            <Camera className="size-4" /> {t('unknown.takePhoto')}
          </Button>
          <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden data-testid="unknown-photo" onChange={(e) => onFile(e.target.files?.[0])} />
          {canAi && (
            <Button disabled={!lastFile} loading={identify.isPending} onClick={() => lastFile && identify.mutate(lastFile)}>
              <Sparkles className="size-4" /> {t('unknown.suggest')}
            </Button>
          )}
        </div>
      </div>
      <p className="text-xs text-ink-500">
        {t('unknown.barcodes')}: {product.barcodes.map((b) => b.raw).join(', ') || '—'}
      </p>

      <Field label={t('product.name')}>{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} autoFocus />}</Field>
      <Field label={t('product.brand')}>{(id) => <Input id={id} value={brand} onChange={(e) => setBrand(e.target.value)} />}</Field>

      <div>
        <div className="mb-1 text-sm font-medium text-ink-700">{t('product.category')}</div>
        <div className="flex flex-wrap gap-2">
          {cats.data?.map((c) => (
            <Chip key={c.id} active={category === c.id} onClick={() => setCategory(category === c.id ? '' : c.id)}>
              {c.name}
            </Chip>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label={t('product.packageSize')}>{(id) => <Input id={id} inputMode="decimal" value={size} onChange={(e) => setSize(e.target.value)} />}</Field>
        <Field label={t('product.packageUnit')}>
          {(id) => (
            <Select id={id} value={unit} onChange={(e) => setUnit(e.target.value as Unit)}>
              <option value="">—</option>
              {UNITS.map((u) => (
                <option key={u} value={u}>
                  {t(`units.${u}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      <Field label={t('product.defaultLocation')}>
        {(id) => (
          <Select id={id} value={location} onChange={(e) => setLocation(e.target.value)}>
            <option value="">—</option>
            {locs.data?.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </Select>
        )}
      </Field>

      <div className="flex flex-wrap justify-between gap-2">
        <Button onClick={onSkip} disabled={remaining < 2}>
          <SkipForward className="size-4" /> {t('unknown.skip')}
        </Button>
        <Button variant="primary" size="lg" disabled={!name.trim()} loading={save.isPending} onClick={() => save.mutate()}>
          {t('common.save')}
        </Button>
      </div>
    </Card>
  )
}

export default function UnknownPage() {
  const { t } = useTranslation()
  const q = useQuery({ queryKey: ['unknown'], queryFn: fetchUnknown })
  const [skip, setSkip] = useState(0)
  const list = q.data ?? []
  const current = list.length ? list[skip % list.length] : null

  return (
    <>
      <PageHeader title={t('nav.unknown')} subtitle={list.length ? t('unknown.remaining', { count: list.length }) : undefined} />
      {q.isLoading ? (
        <ListSkeleton rows={3} />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : !current ? (
        <EmptyState icon={<CheckCircle2 className="size-8" />} title={t('unknown.allDone')} hint={t('unknown.allDoneHint')} />
      ) : (
        <Editor key={current.id} product={current} remaining={list.length} onSkip={() => setSkip((s) => s + 1)} />
      )}
    </>
  )
}
