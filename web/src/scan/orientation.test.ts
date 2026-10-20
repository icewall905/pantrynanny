import { describe, expect, it } from 'vitest'
import { encodeEan13, encodeEan8, renderLuma } from './eanEncode'
import { rotateLuma } from './rotate'
import { OrientationDecoder } from './zxingCore'

/**
 * Worst case: the time budget only allows ONE rotated pass per frame (0° + 90 / 45 / 135 round-robin),
 * so every angle class must be found within 3 consecutive frames.
 */
const MAX_FRAMES = 3
const ANGLES = [0, 15, 30, 45, 60, 90, 120, 135, 180, 225, 270, 315]

function rng(seed: number) {
  let s = seed >>> 0
  return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296)
}

/** Noisy greyish frame with the (rotated) barcode image pasted off-centre. */
function frameWith(code: { luma: Uint8ClampedArray; width: number; height: number }, deg: number, seed: number, size = 520) {
  const rand = rng(seed)
  const f = new Uint8ClampedArray(size * size)
  for (let i = 0; i < f.length; i++) f[i] = 170 + rand() * 60 // paper-ish background with noise
  const r = rotateLuma(code.luma, code.width, code.height, deg, 215)
  const ox = Math.floor((size - r.width) / 2) + 7
  const oy = Math.floor((size - r.height) / 2) - 5
  for (let y = 0; y < r.height; y++)
    for (let x = 0; x < r.width; x++) {
      const v = r.data[y * r.width + x]
      f[(oy + y) * size + ox + x] = Math.max(0, Math.min(255, v * 0.8 + rand() * 25 - 5))
    }
  return f
}

const CASES = [
  { name: 'EAN-13', digits: '5701234567899', format: 'ean_13', img: renderLuma(encodeEan13('5701234567899'), 3, 130, 10, 0.05) },
  { name: 'EAN-8', digits: '96385074', format: 'ean_8', img: renderLuma(encodeEan8('96385074'), 4, 130, 10, 0.05) },
]

describe('orientation-independent decoding (ZXing path)', () => {
  for (const c of CASES) {
    for (const deg of ANGLES) {
      it(`${c.name} at ${deg}° is found within ${MAX_FRAMES} frames`, () => {
        const dec = new OrientationDecoder()
        const frame = frameWith(c.img, deg, deg + 1)
        let found = -1
        for (let i = 0; i < MAX_FRAMES && found < 0; i++) {
          const res = dec.decode(frame, 520, 520, { maxPasses: 1 })
          if (res.length) {
            expect(res).toEqual([{ rawValue: c.digits, format: c.format }])
            found = i
          }
        }
        expect(found).toBeGreaterThanOrEqual(0)
      })
    }
  }

  it('EAN-13 sweep: every 10° step from 0 to 350 is found within 3 frames', () => {
    const missed: number[] = []
    for (let deg = 0; deg < 360; deg += 10) {
      const dec = new OrientationDecoder()
      const frame = frameWith(CASES[0].img, deg, deg + 100)
      let ok = false
      for (let i = 0; i < MAX_FRAMES && !ok; i++) ok = dec.decode(frame, 520, 520, { maxPasses: 1 }).length > 0
      if (!ok) missed.push(deg)
    }
    expect(missed).toEqual([])
  }, 60_000)

  it('the 0° code is found on the very first frame without rotated passes', () => {
    const dec = new OrientationDecoder()
    const res = dec.decode(frameWith(CASES[0].img, 0, 3), 520, 520)
    expect(res).toHaveLength(1)
    expect(dec.last.passes).toBe(0)
  })

  it('degrades to the minimum passes when the clock says the budget is spent', () => {
    let t = 0
    const dec = new OrientationDecoder()
    const frame = frameWith(CASES[0].img, 90, 5) // needs a rotated pass
    dec.decode(frame, 520, 520, { budgetMs: 40, now: () => (t += 60) }) // every clock read costs 60 ms
    expect(dec.last.passes).toBe(1)
  })

  it('a blank frame yields nothing and never throws', () => {
    const dec = new OrientationDecoder()
    for (let i = 0; i < 8; i++) expect(dec.decode(new Uint8ClampedArray(300 * 300).fill(200), 300, 300)).toEqual([])
  })

  it('reports per-frame timing', () => {
    const dec = new OrientationDecoder()
    const frame = frameWith(CASES[0].img, 45, 7)
    const t0 = performance.now()
    for (let i = 0; i < 3; i++) dec.decode(frame, 520, 520, { budgetMs: 1e9 })
    // eslint-disable-next-line no-console
    console.log('timing last frame', JSON.stringify(dec.last), 'wall 3 frames ms', (performance.now() - t0).toFixed(0))
    expect(dec.last.totalMs).toBeGreaterThanOrEqual(dec.last.zeroMs)
  })
})

describe('sticky angle keeps a held rotated code stable', () => {
  it('one count and short gaps at 100 ms/frame with one dropped frame (maxPasses 1)', async () => {
    const { ScanDeduplicator } = await import('./dedupe')
    const frame = frameWith(CASES[0].img, 45, 11)
    const blank = new Uint8ClampedArray(520 * 520).fill(200)
    const dec = new OrientationDecoder()
    const dd = new ScanDeduplicator({ rearmMs: 250 })
    let counts = 0
    let lastHit = -1
    let maxGap = 0
    for (let i = 0; i < 40; i++) {
      const t = i * 100
      const res = dec.decode(i === 20 ? blank : frame, 520, 520, { maxPasses: 1 }) // frame 20 dropped/unreadable
      if (!res.length) continue
      if (lastHit >= 0) maxGap = Math.max(maxGap, t - lastHit)
      lastHit = t
      if (dd.onDetection(res[0].rawValue, t, true)) counts++
    }
    expect(counts).toBe(1)
    expect(maxGap).toBeLessThanOrEqual(200) // with only the round-robin it would be 300+
  })
})
