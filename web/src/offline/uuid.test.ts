import { afterEach, describe, expect, it, vi } from 'vitest'
import { uuid } from './uuid'

afterEach(() => vi.unstubAllGlobals())
describe('uuid', () => {
  it('falls back to getRandomValues when randomUUID is missing (iPadOS 15.0-15.3)', () => {
    vi.stubGlobal('crypto', { getRandomValues: (a: Uint8Array) => a.fill(7) })
    expect(uuid()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  })
})
