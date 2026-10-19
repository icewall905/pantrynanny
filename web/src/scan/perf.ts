// Lightweight scanner performance counters (shown in the hidden debug overlay).
export interface ScanPerf {
  decoder: string
  fps: number
  decodeMs: number
  /** frame grabbed → UI updated, last scan */
  latencyMs: number | null
  lastLatencies: number[]
  frames: number
}

let state: ScanPerf = { decoder: '-', fps: 0, decodeMs: 0, latencyMs: null, lastLatencies: [], frames: 0 }
const listeners = new Set<() => void>()
let windowStart = 0
let windowFrames = 0

function emit() {
  listeners.forEach((f) => f())
}
export const perf = {
  get: () => state,
  subscribe(fn: () => void) {
    listeners.add(fn)
    return () => listeners.delete(fn)
  },
  setDecoder(name: string) {
    state = { ...state, decoder: name }
    emit()
  },
  frame(decodeMs: number, now = performance.now()) {
    windowFrames++
    state = { ...state, frames: state.frames + 1, decodeMs: state.decodeMs ? state.decodeMs * 0.8 + decodeMs * 0.2 : decodeMs }
    if (now - windowStart >= 1000) {
      state = { ...state, fps: Math.round((windowFrames * 1000) / (now - windowStart || 1)) }
      windowStart = now
      windowFrames = 0
      emit()
    }
  },
  latency(ms: number) {
    state = { ...state, latencyMs: ms, lastLatencies: [...state.lastLatencies.slice(-9), ms] }
    emit()
  },
}
