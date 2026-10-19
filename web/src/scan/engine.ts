// Continuous scanner: camera → throttled centre-crop → decoder → duplicate suppression.
import { Camera, CameraError, OpenSuperseded, type Facing } from './camera'
import { createDecoder, type FrameDecoder } from './decoder'
import { readIsTrusted, ScanDeduplicator } from './dedupe'
import { cropRect } from './geometry'
import { perf } from './perf'

export interface ScanEvent {
  value: string
  format: string
  /** performance.now() when the frame containing the code was captured */
  frameAt: number
}

export type EngineState = 'idle' | 'starting' | 'running' | 'paused' | 'error'

export interface EngineOptions {
  video: HTMLVideoElement
  onScan: (e: ScanEvent) => void
  onState?: (s: EngineState, err?: CameraError) => void
  rearmMs?: number
  /** Target decode rate. */
  fps?: number
  maxDecodeWidth?: number
}

type VFCVideo = HTMLVideoElement & {
  requestVideoFrameCallback?: (cb: (now: number, meta: unknown) => void) => number
  cancelVideoFrameCallback?: (id: number) => void
}

export class ScannerEngine {
  readonly dedupe: ScanDeduplicator
  readonly camera = new Camera()
  private decoder: FrameDecoder | null = null
  private state: EngineState = 'idle'
  private wanted = false
  /** Bumped by halt(): a run() that notices a newer value abandons what it just opened. */
  private runGen = 0
  private busy = false
  private lastDecodeAt = 0
  private lastFrameCb = 0
  private frameIndex = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private vfc: number | null = null
  private raf: number | null = null
  private watchdog: ReturnType<typeof setInterval> | null = null
  private restartTimer: ReturnType<typeof setTimeout> | null = null
  private restartDelay = 1000
  private canvas: HTMLCanvasElement | null = null
  private interval: number
  private maxW: number

  private o: EngineOptions
  constructor(o: EngineOptions) {
    this.o = o
    this.dedupe = new ScanDeduplicator({ rearmMs: o.rearmMs })
    this.interval = 1000 / (o.fps ?? 12)
    this.maxW = o.maxDecodeWidth ?? 800
  }

  get torchSupported() {
    return this.camera.torchSupported
  }

  get canSwitchCamera() {
    return this.camera.canSwitch
  }

  /** Switch between rear and front camera; reopens the camera when it is running. */
  setFacing(facing: Facing) {
    if (this.camera.facing === facing) return
    this.camera.facing = facing
    if (this.wanted && document.visibilityState === 'visible') void this.run()
  }

  private set(s: EngineState, err?: CameraError) {
    this.state = s
    this.o.onState?.(s, err)
  }

  async start() {
    this.wanted = true
    document.addEventListener('visibilitychange', this.onVis)
    window.addEventListener('pageshow', this.onVis)
    if (document.visibilityState === 'hidden') return this.set('paused')
    await this.run()
  }

  stop() {
    this.wanted = false
    document.removeEventListener('visibilitychange', this.onVis)
    window.removeEventListener('pageshow', this.onVis)
    this.halt()
    this.decoder?.dispose()
    this.decoder = null
    this.set('idle')
  }

  async setTorch(on: boolean) {
    return this.camera.setTorch(on)
  }

  private onVis = () => {
    if (!this.wanted) return
    if (document.visibilityState === 'hidden') {
      this.halt()
      this.set('paused')
    } else if (this.state === 'starting') {
      return // an open is already in flight
    } else if (this.state !== 'running' || !this.camera.alive) {
      void this.run()
    }
  }

  private halt() {
    this.runGen++
    if (this.timer) clearTimeout(this.timer)
    if (this.restartTimer) clearTimeout(this.restartTimer)
    if (this.watchdog) clearInterval(this.watchdog)
    const v = this.o.video as VFCVideo
    if (this.vfc !== null) v.cancelVideoFrameCallback?.(this.vfc)
    if (this.raf !== null) cancelAnimationFrame(this.raf)
    this.timer = this.restartTimer = this.watchdog = null
    this.vfc = this.raf = null
    this.camera.close()
    this.busy = false
  }

  private async run() {
    this.halt()
    const gen = this.runGen
    const stale = () => gen !== this.runGen || !this.wanted || document.visibilityState === 'hidden'
    this.set('starting')
    try {
      this.decoder ??= await createDecoder()
      if (stale()) return
      await this.camera.open(this.o.video)
    } catch (e) {
      if (e instanceof OpenSuperseded || stale()) return
      const ce = e instanceof CameraError ? e : new CameraError('other', String(e))
      this.set('error', ce)
      // Transient failures (camera busy / killed by iOS) are retried; permission denial is not.
      if (ce.kind !== 'denied' && ce.kind !== 'insecure') this.scheduleRestart()
      return
    }
    if (stale()) {
      this.camera.close() // we were stopped/superseded while the browser was opening the camera
      return
    }
    this.restartDelay = 1000
    this.camera.onEnded = () => {
      if (gen === this.runGen && this.wanted && document.visibilityState === 'visible') {
        this.halt()
        this.scheduleRestart()
      }
    }
    this.lastFrameCb = performance.now()
    this.set('running')
    this.schedule()
    // iOS can freeze the video without ending the track: restart when no frames arrive.
    this.watchdog = setInterval(() => {
      if (!this.wanted || gen !== this.runGen || document.visibilityState !== 'visible') return
      if (this.state === 'running' && performance.now() - this.lastFrameCb > 4000) {
        this.halt()
        void this.run()
      }
    }, 2000)
  }

  private scheduleRestart() {
    if (!this.wanted) return
    this.restartTimer = setTimeout(() => void this.run(), this.restartDelay)
    this.restartDelay = Math.min(this.restartDelay * 2, 10_000)
  }

  private schedule() {
    const v = this.o.video as VFCVideo
    if (v.requestVideoFrameCallback) {
      this.vfc = v.requestVideoFrameCallback(() => this.tick())
      // rVFC stops firing for a stalled video; the watchdog interval in run() detects that and restarts.
    } else {
      this.timer = setTimeout(() => this.tick(), this.interval / 2)
    }
  }

  private tick() {
    this.vfc = null
    if (!this.wanted || this.state !== 'running') return
    const now = performance.now()
    this.lastFrameCb = now
    if (!this.busy && now - this.lastDecodeAt >= this.interval && document.visibilityState === 'visible') {
      this.lastDecodeAt = now
      void this.decodeFrame(now)
    }
    this.schedule()
  }

  private async decodeFrame(frameAt: number) {
    const v = this.o.video
    if (v.readyState < 2 || !v.videoWidth) return
    this.busy = true
    const gen = this.runGen
    try {
      const box = v.getBoundingClientRect()
      const r = cropRect(v.videoWidth, v.videoHeight, box.width, box.height)
      const scale = Math.min(1, this.maxW / r.w)
      const w = Math.max(16, Math.round(r.w * scale))
      const h = Math.max(16, Math.round(r.h * scale))
      this.canvas ??= document.createElement('canvas')
      if (this.canvas.width !== w || this.canvas.height !== h) {
        this.canvas.width = w
        this.canvas.height = h
      }
      const ctx = this.canvas.getContext('2d', { willReadFrequently: true })!
      ctx.drawImage(v, r.x, r.y, r.w, r.h, 0, 0, w, h)
      const t0 = performance.now()
      const found = await this.decoder!.decode({ canvas: this.canvas, ctx, width: w, height: h, index: this.frameIndex++ })
      perf.frame(performance.now() - t0)
      if (gen !== this.runGen || !this.wanted || this.state !== 'running') return // stopped/restarted while decoding
      const t = performance.now()
      for (const f of found) {
        if (this.dedupe.onDetection(f.rawValue, t, readIsTrusted(f.rawValue, f.format))) {
          this.o.onScan({ value: f.rawValue, format: f.format, frameAt })
        }
      }
    } catch {
      /* a failed frame is not fatal */
    } finally {
      this.busy = false
    }
  }
}
