import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, CircleSlash, Loader2, PlugZap, XCircle } from 'lucide-react'
import { get, patch, post } from '../../api/client'
import { useToast } from '../../components/Toast'
import { Button, Card, ErrorState, Field, Input, ListSkeleton, Select, Toggle } from '../../components/ui'

type Feature = 'chat' | 'recipes' | 'photo'

interface AIConfig {
  enabled: boolean
  base_url: string
  model: string
  timeout_s: number
  max_tokens: number
  temperature: number | null
  disable_thinking: boolean
  features: Record<Feature, boolean>
  has_api_key: boolean
  active: boolean
}
interface AIView {
  config: AIConfig
  env: AIConfig
  overridden: string[]
  api_key_source: 'db' | 'env' | null
}
interface Step {
  ok: boolean
  ms?: number
  answer?: string | null
  error?: string | null
  finish_reason?: string | null
  reasoning_chars?: number
  retried_without_thinking?: boolean
  looks_right?: boolean
  models?: string[]
  status?: number
}
interface TestResult {
  base_url: string
  model: string | null
  steps: { models?: Step; text?: Step; vision?: Step }
}

interface Draft {
  enabled: boolean
  base_url: string
  api_key: string
  model: string
  timeout_s: string
  max_tokens: string
  temperature: string
  disable_thinking: boolean
  features: Record<Feature, boolean>
}

const FEATURES: Feature[] = ['chat', 'recipes', 'photo']

function draftFrom(c: AIConfig): Draft {
  return {
    enabled: c.enabled,
    base_url: c.base_url,
    api_key: '',
    model: c.model,
    timeout_s: String(c.timeout_s),
    max_tokens: c.max_tokens ? String(c.max_tokens) : '',
    temperature: c.temperature == null ? '' : String(c.temperature),
    disable_thinking: c.disable_thinking,
    features: { ...c.features },
  }
}

function payload(d: Draft): Record<string, unknown> {
  const num = (s: string) => (s.trim() === '' ? null : Number(s.replace(',', '.')))
  return {
    enabled: d.enabled,
    base_url: d.base_url.trim() || null,
    ...(d.api_key ? { api_key: d.api_key } : {}),
    model: d.model.trim() || null,
    timeout_s: num(d.timeout_s),
    max_tokens: num(d.max_tokens) ?? 0,
    temperature: num(d.temperature),
    disable_thinking: d.disable_thinking,
    features: d.features,
  }
}

function StepRow({ title, step }: { title: string; step?: Step }) {
  const { t } = useTranslation()
  if (!step) return null
  const Icon = step.ok ? CheckCircle2 : XCircle
  return (
    <li className="flex gap-3 py-2.5">
      <Icon className={step.ok ? 'mt-0.5 size-5 shrink-0 text-leaf-600' : 'mt-0.5 size-5 shrink-0 text-tomato-600'} aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        <div className="font-semibold">
          {title}
          {step.ms != null && <span className="ml-2 font-normal text-ink-500">{(step.ms / 1000).toFixed(1)} s</span>}
        </div>
        {step.answer && <div className="truncate text-ink-700">“{step.answer}”</div>}
        {step.models && step.models.length > 0 && <div className="truncate text-ink-500">{step.models.join(', ')}</div>}
        {step.error && <div className="text-tomato-600">{step.error}</div>}
        <div className="text-xs text-ink-500">
          {step.finish_reason && <span>finish_reason: {step.finish_reason} </span>}
          {!!step.reasoning_chars && <span>· {t('adminAi.reasoningChars', { n: step.reasoning_chars })} </span>}
          {step.retried_without_thinking && <span>· {t('adminAi.retried')}</span>}
          {step.looks_right === false && <span>· {t('adminAi.visionWrong')}</span>}
        </div>
      </div>
    </li>
  )
}

export default function AdminAI() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['admin', 'ai'], queryFn: () => get<AIView>('/admin/ai') })
  const [d, setD] = useState<Draft | null>(null)
  const [result, setResult] = useState<TestResult | null>(null)
  useEffect(() => {
    if (q.data && !d) setD(draftFrom(q.data.config))
  }, [q.data, d])

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => patch<AIView>('/admin/ai', body),
    onSuccess: (v) => {
      qc.setQueryData(['admin', 'ai'], v)
      void qc.invalidateQueries({ queryKey: ['ai-status'] })
      setD(draftFrom(v.config))
      toast.push(t('common.saved'), 'success')
    },
    onError: () => toast.push(t('common.saveFailed'), 'error'),
  })
  const test = useMutation({
    mutationFn: (body: Record<string, unknown>) => post<TestResult>('/admin/ai/test', body),
    onSuccess: setResult,
    onError: () => toast.push(t('adminAi.testFailed'), 'error'),
  })

  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data || !d) return <ListSkeleton rows={4} />
  const env = q.data.env
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD({ ...d, [k]: v })
  const models = result?.steps.models?.models ?? []

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="text-lg font-bold">{t('adminAi.title')}</h2>
        <p className="mb-4 text-sm text-ink-500">{t('adminAi.hint')}</p>
        <div className="space-y-4">
          <Toggle checked={d.enabled} onChange={(v) => set('enabled', v)} label={t('adminAi.enabled')} hint={t('adminAi.enabledHint')} />
          <Field label={t('adminAi.baseUrl')} hint={t('adminAi.baseUrlHint', { env: env.base_url || '—' })}>
            {(id) => (
              <Input
                id={id}
                inputMode="url"
                autoCapitalize="none"
                spellCheck={false}
                placeholder="http://192.0.2.20:8080/v1"
                value={d.base_url}
                onChange={(e) => set('base_url', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('adminAi.model')} hint={t('adminAi.modelHint')}>
            {(id) =>
              models.length > 0 ? (
                <Select id={id} value={d.model} onChange={(e) => set('model', e.target.value)}>
                  <option value="">{t('adminAi.modelAuto')}</option>
                  {models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input id={id} spellCheck={false} placeholder={t('adminAi.modelAuto')} value={d.model} onChange={(e) => set('model', e.target.value)} />
              )
            }
          </Field>
          <Field
            label={t('adminAi.apiKey')}
            hint={q.data.config.has_api_key ? t('adminAi.apiKeySet', { source: q.data.api_key_source === 'env' ? 'env' : t('adminAi.saved') }) : t('adminAi.apiKeyHint')}
          >
            {(id) => (
              <Input id={id} type="password" autoComplete="off" placeholder="••••••••" value={d.api_key} onChange={(e) => set('api_key', e.target.value)} />
            )}
          </Field>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t('adminAi.timeout')} hint={t('adminAi.timeoutHint')}>
              {(id) => <Input id={id} inputMode="numeric" value={d.timeout_s} onChange={(e) => set('timeout_s', e.target.value)} />}
            </Field>
            <Field label={t('adminAi.maxTokens')} hint={t('adminAi.maxTokensHint')}>
              {(id) => <Input id={id} inputMode="numeric" placeholder="auto" value={d.max_tokens} onChange={(e) => set('max_tokens', e.target.value)} />}
            </Field>
            <Field label={t('adminAi.temperature')} hint={t('adminAi.temperatureHint')}>
              {(id) => <Input id={id} inputMode="decimal" placeholder="auto" value={d.temperature} onChange={(e) => set('temperature', e.target.value)} />}
            </Field>
          </div>
          <Toggle
            checked={d.disable_thinking}
            onChange={(v) => set('disable_thinking', v)}
            label={t('adminAi.disableThinking')}
            hint={t('adminAi.disableThinkingHint')}
          />
          <div>
            <div className="mb-1 text-sm font-medium text-ink-700">{t('adminAi.features')}</div>
            {FEATURES.map((f) => (
              <Toggle key={f} checked={d.features[f]} onChange={(v) => set('features', { ...d.features, [f]: v })} label={t(`adminAi.feature_${f}`)} />
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(payload(d))}>
              {t('common.save')}
            </Button>
            <Button loading={test.isPending} onClick={() => test.mutate(payload(d))}>
              <PlugZap className="size-4" /> {t('adminAi.test')}
            </Button>
            {q.data.overridden.length > 0 && (
              <Button
                variant="ghost"
                onClick={() =>
                  save.mutate({
                    enabled: null,
                    base_url: null,
                    api_key: '',
                    model: null,
                    timeout_s: null,
                    max_tokens: null,
                    temperature: null,
                    disable_thinking: null,
                    features: { chat: true, recipes: true, photo: true },
                  })
                }
              >
                {t('adminAi.reset')}
              </Button>
            )}
          </div>
        </div>
      </Card>

      {(test.isPending || result) && (
        <Card aria-live="polite">
          <h3 className="mb-1 font-bold">{t('adminAi.results')}</h3>
          {test.isPending ? (
            <p className="flex items-center gap-2 py-2 text-sm text-ink-500">
              <Loader2 className="size-4 animate-spin" /> {t('adminAi.testing')}
            </p>
          ) : result ? (
            <>
              <p className="text-sm text-ink-500">
                {result.base_url || '—'} · {result.model ?? t('adminAi.noModel')}
              </p>
              <ul className="divide-y divide-cream-200">
                <StepRow title={t('adminAi.stepModels')} step={result.steps.models} />
                <StepRow title={t('adminAi.stepText')} step={result.steps.text} />
                <StepRow title={t('adminAi.stepVision')} step={result.steps.vision} />
              </ul>
              {!result.steps.text && !result.steps.models?.ok && (
                <p className="flex items-center gap-2 text-sm text-ink-500">
                  <CircleSlash className="size-4" /> {t('adminAi.stopped')}
                </p>
              )}
            </>
          ) : null}
        </Card>
      )}
    </div>
  )
}
