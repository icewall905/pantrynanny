// Frame decoder: native BarcodeDetector when it really supports EAN-13, else ZXing
// (in a Web Worker when possible, on the main thread otherwise).
import { perf } from './perf'
import { OrientationDecoder, rgbaToLuma, type DecodedBarcode, type FrameTiming } from './zxingCore'

export type { DecodedBarcode }

export interface Frame {
  canvas: HTMLCanvasElement | OffscreenCanvas
  ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D
  width: number
  height: number
  index: number
}

export interface FrameDecoder {
  name: 'native' | 'zxing-worker' | 'zxing-main'
  decode(frame: Frame): Promise<DecodedBarcode[]>
  dispose(): void
}

interface NativeDetector {
  detect(src: CanvasImageSource): Promise<{ rawValue: string; format: string }[]>
}
interface NativeCtor {
  new (opts: { formats: string[] }): NativeDetector
  getSupportedFormats(): Promise<string[]>
}

const WANTED = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'itf']

async function createNative(): Promise<FrameDecoder | null> {
  const Ctor = (globalThis as unknown as { BarcodeDetector?: NativeCtor }).BarcodeDetector
  if (!Ctor) return null
  try {
    const supported = await Ctor.getSupportedFormats()
    if (!supported.includes('ean_13')) return null
    const det = new Ctor({ formats: WANTED.filter((f) => supported.includes(f)) })
    return {
      name: 'native',
      async decode(f) {
        const res = await det.detect(f.canvas as CanvasImageSource)
        return res.map((r) => ({ rawValue: r.rawValue, format: r.format }))
      },
      dispose() {},
    }
  } catch {
    return null
  }
}

function getImageData(f: Frame) {
  return f.ctx.getImageData(0, 0, f.width, f.height)
}

function createZxingMain(): FrameDecoder {
  const core = new OrientationDecoder()
  let luma: Uint8ClampedArray | undefined
  return {
    name: 'zxing-main',
    async decode(f) {
      luma = rgbaToLuma(getImageData(f).data, luma)
      const res = core.decode(luma, f.width, f.height, { maxPasses: 1, budgetMs: 25 }) // main thread: keep the UI responsive
      perf.timing(core.last)
      return res
    },
    dispose() {},
  }
}

function createZxingWorker(): FrameDecoder | null {
  if (typeof Worker === 'undefined') return null
  let worker: Worker
  try {
    worker = new Worker(new URL('./zxing.worker.ts', import.meta.url), { type: 'module' })
  } catch {
    return null
  }
  let id = 0
  const waiting = new Map<number, { resolve(r: DecodedBarcode[]): void; reject(e: unknown): void }>()
  let broken = false
  const fail = (e: unknown) => {
    broken = true
    waiting.forEach((w) => w.reject(e))
    waiting.clear()
  }
  worker.onmessage = (ev: MessageEvent<{ id: number; results: DecodedBarcode[]; timing?: FrameTiming }>) => {
    if (ev.data.timing) perf.timing(ev.data.timing)
    waiting.get(ev.data.id)?.resolve(ev.data.results)
    waiting.delete(ev.data.id)
  }
  worker.onerror = fail
  worker.onmessageerror = fail
  return {
    name: 'zxing-worker',
    decode(f) {
      if (broken) return Promise.reject(new Error('worker broken'))
      const luma = rgbaToLuma(getImageData(f).data)
      const myId = ++id
      return new Promise<DecodedBarcode[]>((resolve, reject) => {
        const timer = setTimeout(() => {
          waiting.delete(myId)
          fail(new Error('worker timeout'))
          reject(new Error('worker timeout'))
        }, 4000)
        waiting.set(myId, {
          resolve: (r) => (clearTimeout(timer), resolve(r)),
          reject: (e) => (clearTimeout(timer), reject(e)),
        })
        worker.postMessage(
          { id: myId, width: f.width, height: f.height, luma: luma.buffer },
          [luma.buffer],
        )
      })
    },
    dispose() {
      worker.terminate()
    },
  }
}

/** Wraps a decoder so a failing worker transparently falls back to main-thread ZXing. */
function withFallback(primary: FrameDecoder): FrameDecoder {
  let current = primary
  let fallback: FrameDecoder | null = null
  return {
    get name() {
      return current.name
    },
    async decode(f) {
      try {
        return await current.decode(f)
      } catch {
        if (current === primary && primary.name !== 'zxing-main') {
          fallback ??= createZxingMain()
          current = fallback
          perf.setDecoder(current.name)
          return current.decode(f)
        }
        return []
      }
    },
    dispose() {
      primary.dispose()
      fallback?.dispose()
    },
  }
}

export async function createDecoder(opts: { forceZxing?: boolean } = {}): Promise<FrameDecoder> {
  const native = opts.forceZxing ? null : await createNative()
  const d = withFallback(native ?? createZxingWorker() ?? createZxingMain())
  perf.setDecoder(d.name)
  return d
}
