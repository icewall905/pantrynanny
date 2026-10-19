import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { jsonError, mockFetch, renderApp } from '../test/utils'
import AssistantPage from './AssistantPage'
import { historyPayload } from '../components/assistant/ChatPanel'

const status = { enabled: true, reachable: true, model: 'm' }
const recipe = {
  title: 'Ærtesuppe',
  description: 'Varm suppe',
  have: ['Ærter'],
  missing: ['Løg', 'Fløde'],
  substitutions: ['Mælk i stedet for fløde'],
  steps: ['Kog ærterne'],
}

beforeEach(() => {
  localStorage.clear()
})

describe('AssistantPage', () => {
  it('shows an unavailable state when the AI is not reachable', async () => {
    mockFetch({ 'GET /ai/status': { enabled: true, reachable: false, model: null } })
    renderApp(<AssistantPage />)
    expect(await screen.findByText('Assistenten er ikke tilgængelig')).toBeInTheDocument()
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
  })

  it('sends a starter question and shows the reply', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      'GET /ai/status': status,
      'POST /ai/chat': { reply: 'Der er **mælk** i køleskabet.', tool_calls: [{ name: 'search_inventory', arguments: {} }], model: 'm' },
    })
    renderApp(<AssistantPage />)
    await user.click(await screen.findByRole('button', { name: 'Hvad har vi i køleskabet?' }))
    expect(await screen.findByText('mælk')).toBeInTheDocument()
    const chat = calls.find((c) => c.path === '/ai/chat')!
    expect((chat.body as { messages: unknown[] }).messages).toEqual([{ role: 'user', content: 'Hvad har vi i køleskabet?' }])
  })

  it('shows proposed actions as buttons and runs one only when tapped', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      'GET /ai/status': status,
      'POST /ai/chat': {
        reply: 'Skal jeg sætte mælk på listen?',
        tool_calls: [{ name: 'propose_add_to_shopping', arguments: {} }],
        model: 'm',
        proposals: [{ id: 'p1', kind: 'shopping_add', label: 'Mælk × 2', payload: { name: 'Mælk', quantity: 2, product_id: 'pm' } }],
      },
      'POST /shopping': { id: 's1' },
    })
    renderApp(<AssistantPage />)
    await user.click(await screen.findByRole('button', { name: 'Hvad har vi i køleskabet?' }))
    const btn = await screen.findByTestId('proposal')
    expect(btn).toHaveTextContent('Sæt på indkøbslisten: Mælk × 2')
    expect(calls.filter((c) => c.path === '/shopping')).toHaveLength(0)
    await user.click(btn)
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST' && c.path === '/shopping')).toHaveLength(1))
    expect(calls.find((c) => c.path === '/shopping')!.body).toEqual({ product_id: 'pm', quantity: 2 })
    await waitFor(() => expect(btn).toBeDisabled())
  })

  it('shows recipes and adds missing items only after an explicit click', async () => {
    const user = userEvent.setup()
    const calls = mockFetch({
      'GET /ai/status': status,
      'POST /ai/recipes': { recipes: [recipe] },
      'POST /shopping': { id: 's1' },
    })
    renderApp(<AssistantPage />)
    await user.click(await screen.findByRole('tab', { name: 'Opskrifter' }))
    await user.click(screen.getByRole('button', { name: /Foreslå opskrifter/ }))
    expect(await screen.findByText('Ærtesuppe')).toBeInTheDocument()
    expect(screen.getByText('Har vi')).toBeInTheDocument()
    expect(screen.getByText('Mangler')).toBeInTheDocument()
    expect(screen.getByText('Alternativer')).toBeInTheDocument()
    expect(screen.queryByText('Kog ærterne')).not.toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/shopping')).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: /Tilføj manglende til indkøbsliste/ }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST' && c.path === '/shopping')).toHaveLength(2))
    expect(calls.filter((c) => c.path === '/shopping').map((c) => (c.body as { name: string }).name)).toEqual(['Løg', 'Fløde'])
    await user.click(screen.getByRole('button', { name: /Vis fremgangsmåde/ }))
    expect(screen.getByText('Kog ærterne')).toBeInTheDocument()
  })

  it('trims long chat history and over-long replies before posting', () => {
    const entries = Array.from({ length: 40 }, (_, i) => ({
      role: (i % 2 === 0 ? 'user' : 'assistant') as 'user' | 'assistant',
      content: i === 39 ? 'x'.repeat(9000) : `m${i}`,
    }))
    entries.push({ role: 'user', content: 'sidst' })
    const out = historyPayload(entries)
    expect(out.length).toBeLessThanOrEqual(12)
    expect(out[0].role).toBe('user')
    expect(out[out.length - 1].content).toBe('sidst')
    expect(out.every((m) => m.content.length <= 4000)).toBe(true)
  })

  it('does not duplicate already-added items when retrying a failed bulk add', async () => {
    const user = userEvent.setup()
    let n = 0
    const calls = mockFetch({
      'GET /ai/status': status,
      'POST /ai/recipes': { recipes: [recipe] },
      'POST /shopping': () => {
        n += 1
        return n === 2 ? jsonError(500) : { id: 's' }
      },
    })
    renderApp(<AssistantPage />)
    await user.click(await screen.findByRole('tab', { name: 'Opskrifter' }))
    await user.click(screen.getByRole('button', { name: /Foreslå opskrifter/ }))
    const add = await screen.findByRole('button', { name: /Tilføj manglende til indkøbsliste/ })
    await user.click(add)
    await waitFor(() => expect(calls.filter((c) => c.path === '/shopping' && c.method === 'POST')).toHaveLength(2))
    await user.click(screen.getByRole('button', { name: /Tilføj manglende til indkøbsliste/ }))
    await waitFor(() => expect(calls.filter((c) => c.path === '/shopping' && c.method === 'POST')).toHaveLength(3))
    expect(calls.filter((c) => c.path === '/shopping' && c.method === 'POST').map((c) => (c.body as { name: string }).name)).toEqual(['Løg', 'Fløde', 'Fløde'])
  })
})
