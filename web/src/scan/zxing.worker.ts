/// <reference lib="webworker" />
import { OrientationDecoder } from './zxingCore'

const dec = new OrientationDecoder()

export interface WorkerRequest {
  id: number
  width: number
  height: number
  luma: ArrayBuffer
}

self.onmessage = (ev: MessageEvent<WorkerRequest>) => {
  const { id, width, height, luma } = ev.data
  const results = dec.decode(new Uint8ClampedArray(luma), width, height)
  ;(self as unknown as Worker).postMessage({ id, results, timing: dec.last })
}
