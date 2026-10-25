import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Category, Location, Product } from '../api/types'
import { mockFetch } from '../test/utils'
import { addDaysISO } from '../lib/expiry'
import './i18n'
import PlaceChips from './PlaceChips'
import { householdDefault, resolvedLocation } from './place'

const loc = (id: string, is_default = false) => ({ id, name: id, icon: null, sort_order: 0, is_default, deleted_at: null }) as Location
const locations = [loc('pantry', true), loc('fridge'), loc('freezer')]
const dairy = { id: 'dairy', name: 'Mejeri', default_expiry_days: 14, default_location_id: 'fridge' } as Category
const milk = { id: 'milk', name: 'Mælk', category_id: 'dairy', default_location_id: null, status: 'known' } as unknown as Product

describe('resolvedLocation', () => {
  it('follows requested -> product -> category -> household default', () => {
    expect(resolvedLocation('freezer', milk, dairy, locations)).toBe('freezer')
    expect(resolvedLocation(null, { ...milk, default_location_id: 'freezer' }, dairy, locations)).toBe('freezer')
    expect(resolvedLocation(null, milk, dairy, locations)).toBe('fridge')
    expect(resolvedLocation(null, null, undefined, locations)).toBe('pantry')
    expect(resolvedLocation('gone', null, undefined, locations)).toBe('pantry')
  })
  it('household default: is_default, then sort_order, then list order', () => {
    const l = (id: string, sort_order: number, is_default = false) => ({ ...loc(id, is_default), sort_order })
    expect(householdDefault([l('a', 2), l('b', 1), l('c', 1)])).toBe('b')
    expect(householdDefault([l('a', 0), l('b', 5, true)])).toBe('b')
    expect(householdDefault([])).toBeNull()
  })
})

describe('PlaceChips', () => {
  it('suggests the category default and places every add of the card with one tap', async () => {
    const calls = mockFetch({ 'POST /inventory/place': { status: 'applied' } })
    const toast = vi.fn()
    render(<PlaceChips ready addOpIds={['op1', 'op2']} product={milk} categories={[dairy]} locations={locations} requestedLocationId={null} toast={toast} />)
    const cat = screen.getByTestId('place-expiry-cat')
    expect(cat).toHaveAttribute('data-suggested', 'true')
    expect(screen.getByTestId('place-loc-fridge')).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(cat)
    await waitFor(() => expect(cat).toHaveAttribute('aria-pressed', 'true'))
    expect(calls.map((c) => (c.body as { add_client_op_id: string }).add_client_op_id)).toEqual(['op1', 'op2'])
    expect(calls[0].body).toMatchObject({ expires_at: addDaysISO(14) })
    expect(toast).toHaveBeenCalledTimes(1)

    // a later location tap keeps the expiry chosen before
    fireEvent.click(screen.getByTestId('place-loc-freezer'))
    await waitFor(() => expect(screen.getByTestId('place-loc-freezer')).toHaveAttribute('aria-pressed', 'true'))
    expect(calls[2].body).toMatchObject({ add_client_op_id: 'op1', location_id: 'freezer', expires_at: addDaysISO(14) })
  })

  it('keeps its choices across a +N tap and places the new add the same way once applied', async () => {
    const calls = mockFetch({ 'POST /inventory/place': { status: 'applied' } })
    const props = { product: milk, categories: [dairy], locations, requestedLocationId: null, toast: vi.fn() }
    const { rerender } = render(<PlaceChips ready addOpIds={['op1']} {...props} />)
    fireEvent.click(screen.getByTestId('place-loc-freezer'))
    await waitFor(() => expect(screen.getByTestId('place-loc-freezer')).toHaveAttribute('aria-pressed', 'true'))
    expect(calls).toHaveLength(1)

    // +1 tapped: still syncing -> chips stay, disabled, choice kept
    rerender(<PlaceChips ready={false} addOpIds={['op1', 'op2']} {...props} />)
    expect(screen.getByTestId('place-loc-freezer')).toBeDisabled()
    expect(screen.getByTestId('place-loc-freezer')).toHaveAttribute('aria-pressed', 'true')
    expect(calls).toHaveLength(1)

    rerender(<PlaceChips ready addOpIds={['op1', 'op2']} {...props} />)
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[1].body).toMatchObject({ add_client_op_id: 'op2', location_id: 'freezer' })
    await waitFor(() => expect(screen.getByTestId('place-loc-freezer')).not.toBeDisabled())
    // tapping where it already is does nothing; the original location moves it back
    fireEvent.click(screen.getByTestId('place-loc-freezer'))
    fireEvent.click(screen.getByTestId('place-loc-fridge'))
    await waitFor(() => expect(calls).toHaveLength(4))
    expect(calls.slice(2).map((c) => c.body)).toMatchObject([
      { add_client_op_id: 'op1', location_id: 'fridge' },
      { add_client_op_id: 'op2', location_id: 'fridge' },
    ])
  })

  it('"none" clears and a failure is only a toast', async () => {
    mockFetch({ 'POST /inventory/place': () => new Response('{"detail":"x"}', { status: 404, headers: { 'content-type': 'application/json' } }) })
    const toast = vi.fn()
    render(<PlaceChips ready addOpIds={['op1']} product={null} categories={[]} locations={locations} requestedLocationId={null} toast={toast} />)
    expect(screen.queryByTestId('place-expiry-cat')).toBeNull()
    fireEvent.click(screen.getByTestId('place-expiry-none'))
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.any(String), 'amber'))
    expect(screen.getByTestId('place-expiry-none')).toHaveAttribute('aria-pressed', 'false')
  })

  it('chip buttons never take focus away from the scanner', () => {
    mockFetch({})
    render(<PlaceChips ready addOpIds={['op1']} product={null} categories={[]} locations={locations} requestedLocationId={null} toast={() => {}} />)
    const ev = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
    screen.getByTestId('place-expiry-d3').dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(true)
  })
})
