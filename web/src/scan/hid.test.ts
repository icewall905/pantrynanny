import { describe, expect, it } from 'vitest'
import { HidBurstDetector, isTypingTarget } from './hid'

function type(d: HidBurstDetector, text: string, start: number, gapMs: number, end = 'Enter') {
  let t = start
  let last: ReturnType<HidBurstDetector['feed']> = { code: null, consumed: false }
  for (const ch of text) {
    last = d.feed(ch, t)
    t += gapMs
  }
  return { result: d.feed(end, t), lastChar: last, end: t }
}

describe('HidBurstDetector', () => {
  it('recognises a fast scanner burst ending in Enter', () => {
    const d = new HidBurstDetector()
    const { result, lastChar } = type(d, '5701234567899', 0, 8)
    expect(result).toEqual({ code: '5701234567899', consumed: true })
    expect(lastChar.consumed).toBe(true)
  })

  it('accepts Tab as the suffix too', () => {
    const d = new HidBurstDetector()
    expect(type(d, '96385074', 0, 15, 'Tab').result.code).toBe('96385074')
  })

  it('ignores a person typing digits and pressing Enter', () => {
    const d = new HidBurstDetector()
    const { result, lastChar } = type(d, '5701234567899', 0, 150)
    expect(result).toEqual({ code: null, consumed: false })
    expect(lastChar.consumed).toBe(false)
  })

  it('ignores short bursts (keyboard shortcuts, auto-repeat)', () => {
    const d = new HidBurstDetector()
    expect(type(d, '123', 0, 5).result.code).toBeNull()
  })

  it('a long pause inside the code starts over', () => {
    const d = new HidBurstDetector()
    let t = 0
    for (const ch of '570123') d.feed(ch, (t += 8))
    t += 500 // the user typed something slowly, then a real scan follows
    expect(type(d, '4006381333931', t, 8).result.code).toBe('4006381333931')
  })

  it('suppresses a bounced trigger but accepts the same product scanned again later', () => {
    const d = new HidBurstDetector()
    const a = type(d, '5701234567899', 0, 8)
    const b = type(d, '5701234567899', a.end + 50, 8)
    expect(b.result.code).toBeNull()
    const c = type(d, '5701234567899', b.end + 1500, 8)
    expect(c.result.code).toBe('5701234567899')
  })

  it('modifier keys inside a burst are ignored', () => {
    const d = new HidBurstDetector()
    let t = 0
    for (const ch of 'ABC-12') {
      d.feed('Shift', t)
      d.feed(ch, (t += 6))
    }
    expect(d.feed('Enter', t + 6).code).toBe('ABC-12')
  })
})

describe('isTypingTarget', () => {
  it('text inputs are typing targets, buttons and checkboxes are not', () => {
    const input = document.createElement('input')
    const box = Object.assign(document.createElement('input'), { type: 'checkbox' })
    expect(isTypingTarget(input)).toBe(true)
    expect(isTypingTarget(document.createElement('textarea'))).toBe(true)
    expect(isTypingTarget(box)).toBe(false)
    expect(isTypingTarget(document.createElement('button'))).toBe(false)
    expect(isTypingTarget(null)).toBe(false)
  })
})
