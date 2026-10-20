// Unknown barcodes: keep the camera frame the scanner saw, so whoever names the product later can
// see what it was. The frame is uploaded as a "snapshot" photo (never replaces a real photo; a
// product image found later replaces it). Kept in IndexedDB until its product exists on the server.
import { openDB, type IDBPDatabase } from 'idb'
import { get, post, qs } from '../api/client'
import type { BarcodeLookupResult } from '../api/types'

interface Snapshot {
  code: string // the raw barcode as scanned
  symbology: string
  blob: Blob
  at: number
}

const MAX_AGE_MS = 7 * 24 * 3600_000
const MAX_EDGE = 1280
let dbp: Promise<IDBPDatabase> | null = null
const db = () => (dbp ??= openDB('pn-snapshots', 1, { upgrade: (d) => void d.createObjectStore('snaps', { keyPath: 'code' }) }))

/** JPEG of the current video frame (downscaled), or null when there is no picture yet. */
export async function grabFrame(video: HTMLVideoElement | null): Promise<Blob | null> {
  if (!video || video.readyState < 2 || !video.videoWidth) return null
  const scale = Math.min(1, MAX_EDGE / Math.max(video.videoWidth, video.videoHeight))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(video.videoWidth * scale)
  canvas.height = Math.round(video.videoHeight * scale)
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.82))
}

/** Remember a frame for an unknown barcode (the first one per barcode wins). */
export async function keepSnapshot(code: string, symbology: string, blob: Blob) {
  try {
    const d = await db()
    if (!(await d.get('snaps', code))) await d.put('snaps', { code, symbology, blob, at: Date.now() } satisfies Snapshot)
  } catch {
    /* storage blocked: the scan itself is unaffected */
  }
}

let running: Promise<void> | null = null

/** Upload every kept frame whose product now exists; safe to call often (runs one at a time). */
export function flushSnapshots(): Promise<void> {
  running ??= flush().finally(() => (running = null))
  return running
}

async function flush() {
  let d: IDBPDatabase
  try {
    d = await db()
  } catch {
    return
  }
  const all = (await d.getAll('snaps')) as Snapshot[]
  for (const s of all) {
    if (Date.now() - s.at > MAX_AGE_MS) {
      await d.delete('snaps', s.code)
      continue
    }
    try {
      const r = await get<BarcodeLookupResult>(`/products/by-barcode/${encodeURIComponent(s.code)}${qs({ lookup: false, symbology: s.symbology })}`, {
        timeoutMs: 6000,
      })
      if (!r.product) continue // the scan has not reached the server yet
      if (!r.product.image_url) {
        const form = new FormData()
        form.append('file', s.blob, 'snapshot.jpg')
        await post(`/products/${r.product.id}/photo?snapshot=true`, form, { timeoutMs: 20000 })
      }
      await d.delete('snaps', s.code)
    } catch {
      return // offline or server busy: try again later
    }
  }
}
