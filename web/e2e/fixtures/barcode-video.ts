// Generates a Y4M clip for Chromium's fake camera (--use-file-for-fake-video-capture).
// Timeline (10 fps, loops): blank 1 s · item A 2 s · blank 1 s · item A again 2 s · blank 1 s · item B 2 s · blank 1 s.
// A held for 2 s must count ONCE; the second A after a gap counts again; B is an unknown product.
import { mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { encodeEan13, renderLuma } from '../../src/scan/eanEncode'

export const BARCODE_A = '5701234567899' // known product "Letmælk" in the mocked backend
export const BARCODE_B = '4006381333931' // unknown product

const W = 480
const H = 360
const FPS = 10

function frame(code: string | null): Buffer {
  const luma = new Uint8Array(W * H).fill(235)
  if (code) {
    const r = renderLuma(encodeEan13(code), 3, 220, 10, 0.1)
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
  const timeline: [string | null, number][] = [
    [null, 1],
    [BARCODE_A, 2],
    [null, 1],
    [BARCODE_A, 2],
    [null, 1],
    [BARCODE_B, 2],
    [null, 1],
  ]
  const chunks: Buffer[] = [Buffer.from(`YUV4MPEG2 W${W} H${H} F${FPS}:1 Ip A1:1 C420jpeg\n`)]
  for (const [code, secs] of timeline) {
    const f = frame(code)
    for (let i = 0; i < secs * FPS; i++) chunks.push(f)
  }
  writeFileSync(file, Buffer.concat(chunks))
  return file
}
