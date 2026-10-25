import { describe, expect, it } from 'vitest'
import { addDaysISO, addMonthsISO, chipDate, EXPIRY_PRESETS, expiryChips } from './expiry'

describe('addDaysISO', () => {
  it('adds calendar days in local time', () => {
    const now = new Date(2026, 0, 30, 23, 30)
    expect(addDaysISO(0, now)).toBe('2026-01-30')
    expect(addDaysISO(3, now)).toBe('2026-02-02')
    expect(addDaysISO(30, now)).toBe('2026-03-01')
  })
  it('is not thrown off by a DST change', () => {
    expect(addDaysISO(1, new Date(2026, 2, 28, 0, 15))).toBe('2026-03-29')
    expect(addDaysISO(1, new Date(2026, 9, 24, 23, 45))).toBe('2026-10-25')
  })
})

describe('expiryChips', () => {
  it('plain presets without a category default', () => {
    expect(expiryChips(null)).toEqual({ chips: EXPIRY_PRESETS, suggested: -1 })
    expect(expiryChips(undefined).suggested).toBe(-1)
  })
  it('highlights a preset that equals the default', () => {
    const r = expiryChips(7)
    expect(r.chips).toBe(EXPIRY_PRESETS)
    expect(r.chips[r.suggested].key).toBe('w1')
  })
  it('adds its own chip before "none" otherwise', () => {
    const r = expiryChips(14)
    expect(r.chips.map((c) => c.key)).toEqual(['d3', 'w1', 'm1', 'm6', null, 'none'])
    expect(r.suggested).toBe(4)
    expect(r.chips[r.suggested]).toEqual({ key: null, days: 14 })
  })
  it('never matches a day count to a month chip', () => {
    for (const n of [30, 31, 180, 182]) {
      const r = expiryChips(n)
      expect(r.chips[r.suggested]).toEqual({ key: null, days: n })
    }
  })
  it('0 days is a real default (today)', () => {
    const r = expiryChips(0)
    expect(r.chips[r.suggested].days).toBe(0)
  })
})

describe('addMonthsISO', () => {
  it('uses calendar months clamped to the month end', () => {
    expect(addMonthsISO(1, new Date(2026, 0, 31, 9))).toBe('2026-02-28')
    expect(addMonthsISO(1, new Date(2028, 0, 31, 9))).toBe('2028-02-29')
    expect(addMonthsISO(1, new Date(2026, 7, 31, 9))).toBe('2026-09-30')
    expect(addMonthsISO(6, new Date(2026, 7, 31, 9))).toBe('2027-02-28')
    expect(addMonthsISO(6, new Date(2026, 9, 25, 9))).toBe('2027-04-25')
  })
})

describe('chipDate', () => {
  it('month chips use calendar months', () => {
    const jan31 = new Date(2026, 0, 31, 9)
    expect(chipDate(EXPIRY_PRESETS.find((c) => c.key === 'm1')!, jan31)).toBe('2026-02-28')
    expect(chipDate(EXPIRY_PRESETS.find((c) => c.key === 'm6')!, new Date(2026, 7, 31, 9))).toBe('2027-02-28')
  })
  it('none clears, others give a date', () => {
    const now = new Date(2026, 4, 1, 9)
    expect(chipDate({ key: 'none', days: null }, now)).toBeNull()
    expect(chipDate({ key: 'd3', days: 3 }, now)).toBe('2026-05-04')
  })
})
