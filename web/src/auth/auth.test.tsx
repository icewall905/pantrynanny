import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { jsonError, mockFetch, renderApp, ME } from '../test/utils'

vi.mock('../pages/ScanPage', () => ({ default: () => <div>SCANNER-SCREEN</div> }))
vi.mock('../offline', () => ({
  enqueueOp: async () => ({}),
  syncNow: async () => {},
  useSyncStatus: () => ({ online: true, pending: 0, syncing: false, lastSyncAt: null, error: null }),
}))

import App from '../App'

const dashboard = {
  totals: { products_in_stock: 7, items: 12 }, low_stock: [], expiring_soon: [], expired: [], recently_added: [],
  recently_consumed: [], unknown_count: 0, shopping_open_count: 0, by_location: [],
}

beforeEach(() => vi.unstubAllGlobals())

describe('auth', () => {
  it('redirects to /login on 401 and logs in with remember=true by default', async () => {
    let authed = false
    const calls = mockFetch({
      'GET /auth/me': () => (authed ? ME : jsonError(401)),
      'POST /auth/login': () => {
        authed = true
        return ME
      },
      'GET /dashboard': dashboard,
      'GET /ai/status': { enabled: false, reachable: false, model: null },
    })
    const user = userEvent.setup()
    renderApp(<App />, '/')
    const name = await screen.findByLabelText('Brugernavn')
    expect(screen.getByRole('checkbox', { name: 'Husk denne enhed' })).toBeChecked()
    await user.type(name, 'anna')
    await user.type(screen.getByLabelText('Adgangskode'), 'hemmeligt')
    await user.click(screen.getByRole('button', { name: 'Log ind' }))
    await waitFor(() =>
      expect(calls.find((c) => c.path === '/auth/login')?.body).toEqual({ username: 'anna', password: 'hemmeligt', remember: true }),
    )
    expect(await screen.findByText(/7 varer på lager/)).toBeInTheDocument()
  })

  it('sends kiosk sessions to /scan for any other route', async () => {
    mockFetch({ 'GET /auth/me': { ...ME, kiosk: true } })
    renderApp(<App />, '/inventory')
    expect(await screen.findByText('SCANNER-SCREEN')).toBeInTheDocument()
  })

  it('does not require auth for /scan (kiosk pairing happens there)', async () => {
    mockFetch({ 'GET /auth/me': () => jsonError(401) })
    renderApp(<App />, '/scan')
    expect(await screen.findByText('SCANNER-SCREEN')).toBeInTheDocument()
  })
})
