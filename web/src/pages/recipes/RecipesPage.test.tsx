import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { Route, Routes, useLocation } from 'react-router-dom'
import { mockFetch, renderApp, ME } from '../../test/utils'
import { AuthProvider } from '../../auth/AuthProvider'
import RecipesPage from './RecipesPage'

const R = (id: string, title: string, extra: Record<string, unknown> = {}) => ({
  id, version: 1, title, description: null, servings: 4, prep_min: 10, cook_min: 20, instructions: [], tags: [], categories: [],
  source_url: null, source_name: null, image_url: null, created_at: '', updated_at: '', ingredients: [], ...extra,
})
const A = (id: string, have: number, required: number) => ({
  recipe_id: id, servings: 4, have, missing: required - have, required, coverage: required ? have / required : 0, uses_expiring: [], items: [],
})
const LIST = [
  { recipe: R('r1', 'Omelet', { tags: ['Quick'], image_url: 'https://img.example/o.jpg', description: 'Fluffy' }), availability: A('r1', 2, 2) },
  { recipe: R('r2', 'Lagkage'), availability: A('r2', 1, 5) },
]

function Draft() {
  const loc = useLocation()
  return <p data-testid="draft">{(loc.state as { draft?: { title: string } } | null)?.draft?.title}</p>
}
const render = (path: string) =>
  renderApp(
    <AuthProvider>
      <Routes>
        <Route path="/recipes" element={<RecipesPage />} />
        <Route path="/recipes/new" element={<Draft />} />
      </Routes>
    </AuthProvider>,
    path,
  )

describe('RecipesPage', () => {
  it('asks for every recipe in "what can we cook" and shows them as cards', async () => {
    let query = ''
    mockFetch({ 'GET /auth/me': ME, 'GET /recipes/suggest': (url: URL) => ((query = url.search), LIST) })
    render('/recipes')
    const cards = await screen.findAllByTestId('recipe-card')
    expect(cards.map((c) => within(c).getByRole('heading').textContent)).toEqual(['Omelet', 'Lagkage'])
    expect(within(cards[0]).getByText('Quick')).toBeTruthy()
    expect(within(cards[1]).getByText('1/5')).toBeTruthy()
    expect(query).toContain('show_all=true')
  })

  it('reads the recipe right away when opened from the browser extension', async () => {
    const calls = mockFetch({
      'GET /auth/me': ME,
      'GET /recipes/suggest': LIST,
      'POST /recipes/import': { title: 'Boller', description: null, servings: 4, prep_min: null, cook_min: null, ingredients: [], instructions: [], tags: [], image_url: null, source_url: 'https://mad.example/boller', source_name: null },
    })
    render(`/recipes?import=${encodeURIComponent('https://mad.example/boller')}`)
    await waitFor(() => expect(screen.getByTestId('draft').textContent).toBe('Boller'))
    expect(calls.filter((c) => c.path === '/recipes/import').map((c) => c.body)).toEqual([{ url: 'https://mad.example/boller' }])
  })
})
