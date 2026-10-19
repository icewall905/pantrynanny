/// <reference lib="webworker" />
import { ZxingDecoderCore } from './zxingCore'

const core = new ZxingDecoderCore()

export interface WorkerRequest {
  id: number
  width: number
  height: number
  luma: ArrayBuffer
  hard: boolean
}

self.onmessage = (ev: MessageEvent<WorkerRequest>) => {
  const { id, width, height, luma, hard } = ev.data
  const t0 = performance.now()
  const results = core.decode(new Uint8ClampedArray(luma), width, height, hard)
  ;(self as unknown as Worker).postMessage({ id, results, ms: performance.now() - t0 })
}
