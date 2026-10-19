import { describe, expect, it } from 'vitest'
import { loadMode, removeTimedOut, saveMode } from './mode'

const mem = () => {
  const m = new Map<string, string>()
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }
}

describe('scan mode', () => {
  it('persists the mode but starts in ADD after reload', () => {
    const s = mem()
    saveMode('remove', s)
    expect(s.getItem('pn.scan.mode')).toBe('remove')
    expect(loadMode(s)).toBe('add')
    expect(s.getItem('pn.scan.mode')).toBe('add')
  })
  it('REMOVE times out after idle minutes only', () => {
    expect(removeTimedOut('remove', 0, 9 * 60_000, 10)).toBe(false)
    expect(removeTimedOut('remove', 0, 10 * 60_000, 10)).toBe(true)
    expect(removeTimedOut('add', 0, 99 * 60_000, 10)).toBe(false)
  })
})
