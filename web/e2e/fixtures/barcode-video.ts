// Generates a Y4M clip for Chromium's fake camera (--use-file-for-fake-video-capture).
// Timeline (10 fps, loops): blank 1 s · item A 2 s · blank 1 s · item A again, rotated 45 degrees, 2 s · blank 1 s · item B 2 s · blank 1 s.
// A held for 2 s must count ONCE; the second A after a gap counts again; B is an unknown product.
import { mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { encodeEan13, renderLuma } from '../../src/scan/eanEncode'
import { rotateLuma } from '../../src/scan/rotate'

export const BARCODE_A = '5701234567899' // known product "Letmælk" in the mocked backend
export const BARCODE_B = '4006381333931' // unknown product

const W = 1280
const H = 720
const FPS = 10

function frame(code: string | null, deg = 0): Buffer {
  const luma = new Uint8Array(W * H).fill(235)
  if (code) {
    // The decode crop is square (0.9 x the visible shorter side). The camera pane gets narrow while a result card is
    // shown (crop ~450 px of this 1280x720 video), so the 345 px wide code and the 343 px diagonal of the 45-degree
    // one must stay below that.
    const base = deg ? renderLuma(encodeEan13(code), 3, 140, 10, 0.1) : renderLuma(encodeEan13(code), 3, 220, 10, 0.1)
    const rot = rotateLuma(base.luma, base.width, base.height, deg, 255)
    const r = { luma: rot.data, width: rot.width, height: rot.height }
    const ox = Math.floor((W - r.width) / 2)
    const oy = Math.floor((H - r.height) / 2)
    for (let y = 0; y < r.height; y++)
      for (let x = 0; x < r.width; x++) luma[(oy + y) * W + ox + x] = Math.max(16, Math.min(235, 16 + (r.luma[y * r.width + x] * 219) / 255))
  }
  const chroma = Buffer.alloc((W / 2) * (H / 2) * 2, 128)
  return Buffer.concat([Buffer.from('FRAME\n'), Buffer.from(luma), chroma])
}

export function writeBarcodeY4m(): string {
  const dir = join(tmpdir(), 'pn-e2e')
  mkdirSync(dir, { recursive: true })
  const file = join(dir, 'barcodes.y4m')
  const timeline: [string | null, number, number?][] = [
    [null, 1],
    [BARCODE_A, 2],
    [null, 1],
    [BARCODE_A, 2, 45],
    [null, 1],
    [BARCODE_B, 2],
    [null, 1],
  ]
  const chunks: Buffer[] = [Buffer.from(`YUV4MPEG2 W${W} H${H} F${FPS}:1 Ip A1:1 C420jpeg\n`)]
  for (const [code, secs, deg] of timeline) {
    const f = frame(code, deg)
    for (let i = 0; i < secs * FPS; i++) chunks.push(f)
  }
  writeFileSync(file, Buffer.concat(chunks))
  return file
}
