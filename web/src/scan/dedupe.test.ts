import { describe, expect, it } from 'vitest'
import { clampRearm, readIsTrusted, ScanDeduplicator } from './dedupe'

describe('ScanDeduplicator (contract §4)', () => {
  it('fires different products consecutively without delay', () => {
    const d = new ScanDeduplicator()
    expect(d.onDetection('A', 0, true)).toBe(true)
    expect(d.onDetection('B', 30, true)).toBe(true)
    expect(d.onDetection('C', 60, true)).toBe(true)
  })

  it('does not re-fire a code held in view, however long', () => {
    const d = new ScanDeduplicator()
    expect(d.onDetection('A', 0, true)).toBe(true)
    for (let t = 100; t <= 20_000; t += 100) expect(d.onDetection('A', t, true)).toBe(false)
  })

  it('re-fires after the code left view for >= rearm (identical items)', () => {
    const d = new ScanDeduplicator({ rearmMs: 600 })
    expect(d.onDetection('MILK', 0, true)).toBe(true)
    expect(d.onDetection('MILK', 100, true)).toBe(false)
    // gap with no detections …
    expect(d.onDetection('MILK', 100 + 599, true)).toBe(false) // < rearm gap
    expect(d.onDetection('MILK', 100 + 599 + 600, true)).toBe(true) // >= rearm gap
  })

  it('tolerates dropped frames shorter than rearm', () => {
    const d = new ScanDeduplicator({ rearmMs: 600 })
    d.onDetection('A', 0, true)
    for (let t = 400; t < 5000; t += 400) expect(d.onDetection('A', t, true)).toBe(false)
  })

  it('alternating products are independent (no global cooldown)', () => {
    const d = new ScanDeduplicator()
    expect(d.onDetection('A', 0, true)).toBe(true)
    expect(d.onDetection('B', 50, true)).toBe(true)
    expect(d.onDetection('A', 100, true)).toBe(false) // A still within rearm
    expect(d.onDetection('B', 150, true)).toBe(false)
  })

  it('mode switch (clear) lets the item in view count again only after clear', () => {
    const d = new ScanDeduplicator()
    d.onDetection('A', 0, true)
    d.clear()
    expect(d.onDetection('A', 100, true)).toBe(true)
  })

  it('garbage-collects entries older than 10 s', () => {
    const d = new ScanDeduplicator({ rearmMs: 3000 })
    d.onDetection('A', 0, true)
    expect(d.onDetection('B', 10_000, true)).toBe(true)
    expect(d.onDetection('A', 10_050, true)).toBe(true)
  })

  it('requires two reads within 250 ms for untrusted (bad checksum) codes', () => {
    const d = new ScanDeduplicator()
    expect(d.onDetection('X', 0, false)).toBe(false)
    expect(d.onDetection('X', 100, false)).toBe(true)
    expect(d.onDetection('X', 200, false)).toBe(false) // held
    const e = new ScanDeduplicator()
    expect(e.onDetection('Y', 0, false)).toBe(false)
    expect(e.onDetection('Y', 400, false)).toBe(false) // too far apart: starts a new window
    expect(e.onDetection('Y', 500, false)).toBe(true)
  })

  it('clamps rearm to 250–3000', () => {
    expect(clampRearm(10)).toBe(250)
    expect(clampRearm(99999)).toBe(3000)
    expect(clampRearm(undefined)).toBe(600)
  })

  it('readIsTrusted: checksum for EAN/UPC lengths, passes other symbologies', () => {
    expect(readIsTrusted('5701234567899', 'ean_13')).toBe(true)
    expect(readIsTrusted('5701234567898', 'ean_13')).toBe(false)
    expect(readIsTrusted('HELLO', 'code_128')).toBe(true)
    expect(readIsTrusted('12345', 'ean_13')).toBe(false)
  })
})
