import { describe, expect, it } from 'vitest'
import { cropRect } from './geometry'

describe('cropRect', () => {
  it('centres the frame and respects object-fit: cover', () => {
    // 16:9 video in a square box: only the middle 9/16 of the width is visible
    const r = cropRect(1280, 720, 500, 500, { w: 1, h: 1 })
    expect(r.h).toBeCloseTo(720)
    expect(r.w).toBeCloseTo(720)
    expect(r.x).toBeCloseTo(280)
  })
  it('falls back to the full frame without sizes', () => {
    expect(cropRect(640, 480, 0, 0)).toEqual({ x: 0, y: 0, w: 640, h: 480 })
  })
})

describe('cropRect square frame', () => {
  it('uses the same pixel size for both sides', () => {
    const r = cropRect(1280, 720, 800, 500, { w: 0.8, h: 0.8, square: true })
    expect(r.w).toBeCloseTo(r.h)
    expect(r.h).toBeCloseTo(720 * 0.8, 0)
    expect(r.x + r.w / 2).toBeCloseTo(640)
  })
})
