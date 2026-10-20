import { describe, expect, it } from 'vitest'
import { LastCounted } from './lastCounted'
import type { ScanMode } from './mode'

/** Tiny model of handleScan: returns the counted codes. */
function run(steps: ({ scan: string; mode?: ScanMode; session?: string | null } | { undo: string } | { reset: true })[]) {
  const lc = new LastCounted()
  const counted: string[] = []
  let op = 0
  const ops: string[] = []
  let mode: ScanMode = 'add'
  for (const s of steps) {
    if ('undo' in s) lc.undone(s.undo)
    else if ('reset' in s) lc.reset()
    else {
      mode = s.mode ?? mode
      const sess = s.session === undefined ? 's1' : s.session
      if (lc.isRepeat(s.scan, mode, sess)) continue
      const id = `op${++op}`
      ops.push(id)
      lc.record(s.scan, mode, sess, id)
      counted.push(s.scan)
    }
  }
  return counted
}

describe('LastCounted', () => {
  it('same code twice (long gap in between) counts once', () => {
    expect(run([{ scan: 'A' }, { scan: 'A' }])).toEqual(['A'])
  })
  it('A, B, A counts three times', () => {
    expect(run([{ scan: 'A' }, { scan: 'B' }, { scan: 'A' }])).toEqual(['A', 'B', 'A'])
  })
  it('A, mode switch, A counts in each mode', () => {
    expect(run([{ scan: 'A', mode: 'add' }, { scan: 'A', mode: 'remove' }, { scan: 'A', mode: 'remove' }])).toEqual(['A', 'A'])
    expect(run([{ scan: 'A', mode: 'add' }, { reset: true }, { scan: 'A', mode: 'add' }])).toEqual(['A', 'A'])
  })
  it('A, undo of that scan, A counts again', () => {
    expect(run([{ scan: 'A' }, { undo: 'op1' }, { scan: 'A' }])).toEqual(['A', 'A'])
  })
  it('undo of another op does not reset', () => {
    expect(run([{ scan: 'A' }, { undo: 'op99' }, { scan: 'A' }])).toEqual(['A'])
  })
  it('a new scan session counts the same code again', () => {
    expect(run([{ scan: 'A', session: 's1' }, { scan: 'A', session: 's2' }])).toEqual(['A', 'A'])
    expect(run([{ scan: 'A', session: 's1' }, { scan: 'A', session: null }])).toEqual(['A', 'A'])
  })
})
