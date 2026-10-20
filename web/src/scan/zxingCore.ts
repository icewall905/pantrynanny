// ZXing decoding on raw luminance bytes. DOM-free so it runs in a Web Worker and in tests.
import {
  BarcodeFormat,
  BinaryBitmap,
  DecodeHintType,
  HybridBinarizer,
  LuminanceSource,
  MultiFormatReader,
} from '@zxing/library'
import { rotateLuma } from './rotate'

export interface DecodedBarcode {
  rawValue: string
  /** BarcodeDetector-style format name, e.g. ean_13 */
  format: string
}

class GrayLuminanceSource extends LuminanceSource {
  private data: Uint8ClampedArray
  constructor(data: Uint8ClampedArray, width: number, height: number) {
    super(width, height)
    this.data = data
  }
  getRow(y: number, row?: Uint8ClampedArray) {
    const w = this.getWidth()
    const out = row && row.length >= w ? row : new Uint8ClampedArray(w)
    out.set(this.data.subarray(y * w, y * w + w))
    return out
  }
  getMatrix() {
    return this.data
  }
  invert() {
    const inv = new Uint8ClampedArray(this.data.length)
    for (let i = 0; i < inv.length; i++) inv[i] = 255 - this.data[i]
    return new GrayLuminanceSource(inv, this.getWidth(), this.getHeight())
  }
}

const FORMATS = [
  BarcodeFormat.EAN_13,
  BarcodeFormat.EAN_8,
  BarcodeFormat.UPC_A,
  BarcodeFormat.UPC_E,
  BarcodeFormat.CODE_128,
  BarcodeFormat.ITF,
]

const NAMES: Partial<Record<BarcodeFormat, string>> = {
  [BarcodeFormat.EAN_13]: 'ean_13',
  [BarcodeFormat.EAN_8]: 'ean_8',
  [BarcodeFormat.UPC_A]: 'upc_a',
  [BarcodeFormat.UPC_E]: 'upc_e',
  [BarcodeFormat.CODE_128]: 'code_128',
  [BarcodeFormat.ITF]: 'itf',
}

function makeReader(tryHarder: boolean) {
  const r = new MultiFormatReader()
  const hints = new Map<DecodeHintType, unknown>()
  hints.set(DecodeHintType.POSSIBLE_FORMATS, FORMATS)
  hints.set(DecodeHintType.TRY_HARDER, tryHarder)
  r.setHints(hints)
  return r
}

// @zxing/library logs a console.warn (with a stack) for every frame without a code; with several passes per
// frame that is thousands of warnings per minute. Drop just that one message.
let quieted = false
function quietZxing() {
  if (quieted) return
  quieted = true
  const warn = console.warn.bind(console)
  console.warn = (...a: unknown[]) => {
    if (typeof a[0] === 'string' && a[0].startsWith('MultiFormatReader: non-ReaderException')) return
    warn(...a)
  }
}

export class ZxingDecoderCore {
  constructor() {
    quietZxing()
  }
  private fast = makeReader(false)
  private hard = makeReader(true)

  /** `luma` = width*height grayscale bytes. TRY_HARDER is used only when `hard` is set. */
  decode(luma: Uint8ClampedArray, width: number, height: number, hard = false): DecodedBarcode[] {
    const bitmap = new BinaryBitmap(new HybridBinarizer(new GrayLuminanceSource(luma, width, height)))
    try {
      const res = (hard ? this.hard : this.fast).decodeWithState(bitmap)
      return [{ rawValue: res.getText(), format: NAMES[res.getBarcodeFormat()] ?? 'other' }]
    } catch {
      return [] // NotFoundException etc.
    }
  }
}

/**
 * Angles tried after the 0° pass, in round-robin order. 180/270 equal 0/90 for 1D codes (ZXing reads rows
 * in both directions). Together with the 0° pass these 4 classes are 45° apart: a code is read when it is
 * within roughly +-20 degrees of a pass (measured on synthetic EAN-13/8 at 5 degree steps: every angle is
 * found within 3 frames at 1 rotated pass per frame). Extra angles (22.5, 67.5, ...) can be appended if
 * real-world blur turns out to narrow that tolerance - they only lengthen the cycle.
 */
export const ROTATION_ANGLES = [90, 45, 135]

export interface FrameTiming {
  /** ms spent on the 0° pass */
  zeroMs: number
  /** total ms for the frame (0° plus rotated passes) */
  totalMs: number
  /** rotated passes executed */
  passes: number
}

export interface MultiOptions {
  /** soft per-frame time budget; rotated passes stop when the next one is expected to exceed it */
  budgetMs?: number
  /** at least this many rotated passes per frame even when over budget */
  minPasses?: number
  maxPasses?: number
  /** clock, injectable for tests */
  now?: () => number
}

/**
 * Orientation-independent decoding: 0° every frame, plus a round-robin of rotated passes. All passes use the
 * fast reader (32 sampled rows): TRY_HARDER samples 256 rows, ~10x slower (>100 ms on a 520 px frame), which is
 * not affordable per frame. The rotation passes replace what TRY_HARDER used to buy us.
 */
export class OrientationDecoder {
  private core = new ZxingDecoderCore()
  private frameNo = 0
  private next = 0
  /** moving average of one rotated pass (rotate + decode) in ms */
  private passMs = 0
  last: FrameTiming = { zeroMs: 0, totalMs: 0, passes: 0 }

  decode(luma: Uint8ClampedArray, width: number, height: number, o: MultiOptions = {}): DecodedBarcode[] {
    const { budgetMs = 40, minPasses = 1, maxPasses = 3, now = () => performance.now() } = o
    const t0 = now()
    this.frameNo++
    const r0 = this.core.decode(luma, width, height)
    const t1 = now()
    this.last = { zeroMs: t1 - t0, totalMs: t1 - t0, passes: 0 }
    if (r0.length) return r0
    for (let i = 0; i < maxPasses; i++) {
      const ts = now()
      if (i >= minPasses && ts - t0 + this.passMs > budgetMs) break
      const angle = ROTATION_ANGLES[this.next]
      this.next = (this.next + 1) % ROTATION_ANGLES.length
      const rot = rotateLuma(luma, width, height, angle)
      const res = this.core.decode(rot.data, rot.width, rot.height)
      const te = now()
      this.passMs = this.passMs ? this.passMs * 0.7 + (te - ts) * 0.3 : te - ts
      this.last = { zeroMs: t1 - t0, totalMs: te - t0, passes: i + 1 }
      if (res.length) return res
    }
    return []
  }
}

/** RGBA → luminance (integer BT.601 approximation). */
export function rgbaToLuma(rgba: Uint8ClampedArray, out?: Uint8ClampedArray): Uint8ClampedArray {
  const n = rgba.length >> 2
  const l = out && out.length === n ? out : new Uint8ClampedArray(n)
  for (let i = 0, j = 0; i < n; i++, j += 4) l[i] = (rgba[j] * 77 + rgba[j + 1] * 150 + rgba[j + 2] * 29) >> 8
  return l
}
