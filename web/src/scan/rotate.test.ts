import { describe, expect, it } from 'vitest'
import { rotatedSize, rotateLuma } from './rotate'

function img(w: number, h: number) {
  const d = new Uint8ClampedArray(w * h)
  for (let i = 0; i < d.length; i++) d[i] = i
  return d
}

describe('rotateLuma', () => {
  it('0° returns the input untouched', () => {
    const s = img(4, 3)
    const r = rotateLuma(s, 4, 3, 0)
    expect(r.data).toBe(s)
    expect(rotateLuma(s, 4, 3, 360).data).toBe(s)
  })
  it('90° clockwise moves the top-left pixel to the top-right', () => {
    // 3x2:  0 1 2 / 3 4 5   ->  cw 90 -> 2x3:  3 0 / 4 1 / 5 2
    const r = rotateLuma(img(3, 2), 3, 2, 90)
    expect([r.width, r.height]).toEqual([2, 3])
    expect(Array.from(r.data)).toEqual([3, 0, 4, 1, 5, 2])
  })
  it('270° is the inverse of 90°, 180° reverses', () => {
    const s = img(5, 3)
    const r = rotateLuma(rotateLuma(s, 5, 3, 90).data, 3, 5, 270)
    expect(Array.from(r.data)).toEqual(Array.from(s))
    expect(Array.from(rotateLuma(s, 5, 3, 180).data)).toEqual(Array.from(s).reverse())
    expect(Array.from(rotateLuma(s, 5, 3, -90).data)).toEqual(Array.from(rotateLuma(s, 5, 3, 270).data))
  })
  it('sizes the buffer to contain the rotated image', () => {
    expect(rotatedSize(100, 40, 90)).toEqual({ width: 40, height: 100 })
    const s = rotatedSize(100, 40, 45)
    expect(s.width).toBe(Math.ceil(140 * Math.SQRT1_2))
    expect(s.height).toBe(s.width)
    const r = rotateLuma(new Uint8ClampedArray(100 * 40), 100, 40, 30)
    expect(r.data.length).toBe(r.width * r.height)
  })
  it('keeps all content: a dark bar survives a 45° turn and corners are filled', () => {
    const w = 60
    const h = 20
    const s = new Uint8ClampedArray(w * h).fill(255)
    for (let y = 0; y < h; y++) for (let x = 25; x < 35; x++) s[y * w + x] = 0
    const r = rotateLuma(s, w, h, 45)
    expect(r.data[0]).toBe(255) // corner outside the source
    const dark = r.data.filter((v) => v < 60).length
    expect(dark).toBeGreaterThan(10 * 20 * 0.8)
    expect(dark).toBeLessThan(10 * 20 * 1.2)
  })
  it('rotating 45° twice equals rotating 90° (centre line of a bar)', () => {
    const w = 41
    const s = new Uint8ClampedArray(w * w).fill(255)
    for (let x = 0; x < w; x++) s[20 * w + x] = 0 // horizontal line through the centre
    const a = rotateLuma(s, w, w, 90)
    // after 90° the line is vertical through column 20
    for (let y = 0; y < a.height; y++) expect(a.data[y * a.width + 20]).toBe(0)
  })
})
