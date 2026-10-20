// Grayscale image rotation on raw luma buffers (no canvas), used for orientation-independent 1D decoding
// inside the Web Worker. Rotation is clockwise in image coordinates (y down), around the image centre,
// into a buffer big enough to contain the whole rotated image.

export interface LumaImage {
  data: Uint8ClampedArray
  width: number
  height: number
}

/** Size of the buffer that contains a w×h image rotated by `deg`. */
export function rotatedSize(w: number, h: number, deg: number): { width: number; height: number } {
  const a = (norm(deg) * Math.PI) / 180
  const c = Math.abs(Math.cos(a))
  const s = Math.abs(Math.sin(a))
  // snap float noise (cos 90° = 6e-17) so right angles give exact sizes
  const fix = (v: number) => Math.ceil(Math.round(v * 1e6) / 1e6)
  return { width: fix(w * c + h * s), height: fix(w * s + h * c) }
}

function norm(deg: number) {
  return ((deg % 360) + 360) % 360
}

/**
 * Rotate `src` (w×h) clockwise by `deg`. Right angles are exact pixel moves, other angles use bilinear
 * interpolation. Pixels that fall outside the source are `fill` (white = quiet zone by default).
 * 0° returns the input buffer itself (no copy).
 */
export function rotateLuma(src: Uint8ClampedArray, w: number, h: number, deg: number, fill = 255, reuse?: Map<number, Uint8ClampedArray>): LumaImage {
  // optional per-size buffer cache so the per-frame passes do not allocate (the result is only valid until the next call)
  const alloc = (n: number) => {
    if (!reuse) return new Uint8ClampedArray(n)
    let b = reuse.get(n)
    if (!b) reuse.set(n, (b = new Uint8ClampedArray(n)))
    return b
  }
  const d = norm(deg)
  if (d === 0) return { data: src, width: w, height: h }
  if (d === 90 || d === 270) {
    const out = alloc(w * h)
    // 90° cw: dst(x', y') = src(x = y', y = h-1-x'); dst is h wide, w tall
    if (d === 90) {
      for (let y = 0; y < w; y++) for (let x = 0; x < h; x++) out[y * h + x] = src[(h - 1 - x) * w + y]
    } else {
      for (let y = 0; y < w; y++) for (let x = 0; x < h; x++) out[y * h + x] = src[x * w + (w - 1 - y)]
    }
    return { data: out, width: h, height: w }
  }
  if (d === 180) {
    const out = alloc(w * h)
    for (let i = 0, n = w * h; i < n; i++) out[i] = src[n - 1 - i]
    return { data: out, width: w, height: h }
  }
  const { width: W, height: H } = rotatedSize(w, h, d)
  const out = alloc(W * H)
  const a = (d * Math.PI) / 180
  const cos = Math.cos(a)
  const sin = Math.sin(a)
  const scx = (w - 1) / 2
  const scy = (h - 1) / 2
  const dcx = (W - 1) / 2
  const dcy = (H - 1) / 2
  const maxX = w - 1
  const maxY = h - 1
  for (let y = 0; y < H; y++) {
    const dy = y - dcy
    // source position for dst x = 0
    let sx = scx + (-dcx * cos + dy * sin)
    let sy = scy + (dcx * sin + dy * cos)
    const row = y * W
    for (let x = 0; x < W; x++, sx += cos, sy -= sin) {
      if (sx < 0 || sy < 0 || sx > maxX || sy > maxY) {
        out[row + x] = fill
        continue
      }
      const x0 = sx | 0
      const y0 = sy | 0
      const fx = sx - x0
      const fy = sy - y0
      const x1 = x0 < maxX ? x0 + 1 : x0
      const y1 = y0 < maxY ? y0 + 1 : y0
      const i0 = y0 * w
      const i1 = y1 * w
      const top = src[i0 + x0] + (src[i0 + x1] - src[i0 + x0]) * fx
      const bot = src[i1 + x0] + (src[i1 + x1] - src[i1 + x0]) * fx
      out[row + x] = top + (bot - top) * fy + 0.5
    }
  }
  return { data: out, width: W, height: H }
}
