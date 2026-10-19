import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation } from '@tanstack/react-query'
import { Bot, Loader2, RotateCcw, Send, User } from 'lucide-react'
import { ApiError, post } from '../../api/client'
import type { ChatMessage, ChatReply } from '../../api/types'
import { Button, Card, Chip } from '../ui'
import { cn } from '../../lib/format'

/** Tiny safe renderer for the assistant's light markdown (bold + bullet lists). Never uses innerHTML. */
export function renderReply(text: string): ReactNode {
  const inline = (s: string) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith('**') && part.endsWith('**') && part.length > 4 ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>,
    )
  return text.split('\n').map((line, i) => {
    const m = /^\s*[-*•]\s+(.*)$/.exec(line)
    if (m) return <li key={i} className="ml-5 list-disc">{inline(m[1])}</li>
    if (!line.trim()) return <div key={i} className="h-2" />
    return <p key={i}>{inline(line)}</p>
  })
}

export function errorKey(e: unknown): string {
  if (e instanceof ApiError && e.code === 'ai_unavailable') return 'assistant.errorUnavailable'
  if (e instanceof ApiError && e.status === 429) return 'assistant.errorTooMany'
  return 'assistant.errorGeneric'
}

interface Entry extends ChatMessage {
  tools?: string[]
}

export default function ChatPanel({ locale }: { locale: 'da' | 'en' }) {
  const { t } = useTranslation()
  const [entries, setEntries] = useState<Entry[]>([])
  const [text, setText] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  const ask = useMutation({
    mutationFn: (messages: ChatMessage[]) =>
      post<ChatReply>('/ai/chat', { messages, locale }, { timeoutMs: 180_000 }),
    onSuccess: (r) =>
      setEntries((l) => [...l, { role: 'assistant', content: r.reply, tools: [...new Set(r.tool_calls.map((c) => c.name))] }]),
  })

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' })
  }, [entries.length, ask.isPending, ask.isError])

  const send = (content: string) => {
    const q = content.trim()
    if (!q || ask.isPending) return
    const next = [...entries, { role: 'user' as const, content: q }]
    setEntries(next)
    setText('')
    ask.mutate(next.map(({ role, content: c }) => ({ role, content: c })))
  }
  const retry = () => ask.mutate(entries.map(({ role, content: c }) => ({ role, content: c })))

  const starters = [t('assistant.starter1'), t('assistant.starter2'), t('assistant.starter3'), t('assistant.starter4')]

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-ink-500">{t('assistant.readOnly')}</p>
      {entries.length === 0 && (
        <div>
          <h2 className="mb-2 text-sm font-semibold text-ink-700">{t('assistant.starters')}</h2>
          <div className="flex flex-wrap gap-2">
            {starters.map((s) => (
              <Chip key={s} onClick={() => send(s)}>
                {s}
              </Chip>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-3" aria-live="polite">
        {entries.map((m, i) => (
          <Card key={i} className={cn('flex gap-3', m.role === 'user' ? 'bg-leaf-50' : '')}>
            <div className="mt-0.5 text-leaf-600" aria-hidden>
              {m.role === 'user' ? <User className="size-5" /> : <Bot className="size-5" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold text-ink-500">
                {m.role === 'user' ? t('assistant.you') : t('assistant.assistantName')}
              </div>
              <div className="space-y-1 break-words text-sm">{m.role === 'user' ? <p>{m.content}</p> : renderReply(m.content)}</div>
              {m.tools && m.tools.length > 0 && (
                <div className="mt-2 text-xs text-ink-300">{t('assistant.usedTools', { tools: m.tools.join(', ') })}</div>
              )}
            </div>
          </Card>
        ))}
        {ask.isPending && (
          <Card role="status" className="flex items-center gap-3 text-sm text-ink-700">
            <Loader2 className="size-5 animate-spin text-leaf-600" aria-hidden />
            {t('assistant.thinking')}
          </Card>
        )}
        {ask.isError && (
          <Card role="alert" className="flex flex-wrap items-center gap-3 bg-tomato-50 text-sm text-tomato-600">
            <span className="flex-1">{t(errorKey(ask.error))}</span>
            <Button size="sm" onClick={retry}>
              <RotateCcw className="size-4" aria-hidden /> {t('assistant.retry')}
            </Button>
          </Card>
        )}
        <div ref={endRef} />
      </div>

      <form
        className="sticky bottom-20 flex gap-2 rounded-2xl bg-cream-50/90 py-2 backdrop-blur md:bottom-2"
        onSubmit={(e) => {
          e.preventDefault()
          send(text)
        }}
      >
        <input
          aria-label={t('assistant.inputLabel')}
          placeholder={t('assistant.inputPlaceholder')}
          value={text}
          maxLength={2000}
          onChange={(e) => setText(e.target.value)}
          className="min-h-11 min-w-0 flex-1 rounded-xl border border-ink-300/60 bg-white px-3 text-base placeholder:text-ink-300 focus:border-leaf-500 sm:text-sm"
        />
        <Button type="submit" variant="primary" disabled={!text.trim() || ask.isPending}>
          <Send className="size-4" aria-hidden /> {t('assistant.send')}
        </Button>
        {entries.length > 0 && (
          <Button
            onClick={() => {
              setEntries([])
              ask.reset()
            }}
            disabled={ask.isPending}
          >
            {t('assistant.newChat')}
          </Button>
        )}
      </form>
    </div>
  )
}
