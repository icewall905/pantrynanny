// ZXing decoding on raw luminance bytes. DOM-free so it runs in a Web Worker and in tests.
import {
  BarcodeFormat,
  BinaryBitmap,
  DecodeHintType,
  HybridBinarizer,
  LuminanceSource,
  MultiFormatReader,
} from '@zxing/library'

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

export class ZxingDecoderCore {
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

/** RGBA → luminance (integer BT.601 approximation). */
export function rgbaToLuma(rgba: Uint8ClampedArray, out?: Uint8ClampedArray): Uint8ClampedArray {
  const n = rgba.length >> 2
  const l = out && out.length === n ? out : new Uint8ClampedArray(n)
  for (let i = 0, j = 0; i < n; i++, j += 4) l[i] = (rgba[j] * 77 + rgba[j + 1] * 150 + rgba[j + 2] * 29) >> 8
  return l
}
