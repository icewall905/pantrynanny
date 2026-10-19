import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Camera, OpenSuperseded } from './camera'
import { ScannerEngine } from './engine'

interface FakeTrack {
  stop: ReturnType<typeof vi.fn>
  readyState: string
  getSettings: () => object
  getCapabilities: () => object
  addEventListener: () => void
}
function fakeStream() {
  const track: FakeTrack = {
    stop: vi.fn(() => void (track.readyState = 'ended')),
    readyState: 'live',
    getSettings: () => ({ facingMode: 'environment' }),
    getCapabilities: () => ({}),
    addEventListener: () => {},
  }
  return { track, stream: { getTracks: () => [track], getVideoTracks: () => [track] } as unknown as MediaStream }
}
function deferredGum() {
  const calls: { resolve: (s: ReturnType<typeof fakeStream>) => void; made: ReturnType<typeof fakeStream> | null }[] = []
  const gum = vi.fn(
    () =>
      new Promise<MediaStream>((res) => {
        const c = { made: null as ReturnType<typeof fakeStream> | null, resolve: () => {} }
        c.resolve = () => {
          c.made = fakeStream()
          res(c.made.stream)
        }
        calls.push(c as never)
      }),
  )
  Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia: gum, enumerateDevices: async () => [] }, configurable: true })
  return { gum, calls }
}
const flush = () => new Promise((r) => setTimeout(r, 0))

let video: HTMLVideoElement
beforeEach(() => {
  video = document.createElement('video')
  video.play = () => Promise.resolve()
})
afterEach(() => vi.restoreAllMocks())

describe('Camera.open cancellation', () => {
  it('a superseded open stops its stream and keeps only the newest', async () => {
    const { calls } = deferredGum()
    const cam = new Camera()
    const first = cam.open(video)
    const firstP = first.catch((e) => e)
    const second = cam.open(video)
    calls[0].resolve(null as never)
    calls[1].resolve(null as never)
    expect(await firstP).toBeInstanceOf(OpenSuperseded)
    await second
    expect(calls[0].made!.track.stop).toHaveBeenCalled()
    expect(calls[1].made!.track.stop).not.toHaveBeenCalled()
    expect(cam.alive).toBe(true)
  })
  it('close() during a pending open discards the stream', async () => {
    const { calls } = deferredGum()
    const cam = new Camera()
    const p = cam.open(video).catch((e) => e)
    cam.close()
    calls[0].resolve(null as never)
    expect(await p).toBeInstanceOf(OpenSuperseded)
    expect(calls[0].made!.track.stop).toHaveBeenCalled()
    expect(cam.alive).toBe(false)
  })
})

describe('ScannerEngine lifecycle', () => {
  it('stop() while the camera is opening leaves no running camera and never reopens', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'setInterval', 'clearTimeout', 'clearInterval'] })
    const { gum, calls } = deferredGum()
    const states: string[] = []
    const engine = new ScannerEngine({ video, onScan: () => {}, onState: (s) => states.push(s) })
    const started = engine.start()
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(0)
    expect(gum).toHaveBeenCalledTimes(1)
    engine.stop()
    calls[0].resolve(null as never)
    await started
    await vi.advanceTimersByTimeAsync(20_000) // would be long enough for watchdog/restart timers
    expect(calls[0].made!.track.stop).toHaveBeenCalled()
    expect(gum).toHaveBeenCalledTimes(1)
    expect(states.at(-1)).toBe('idle')
    expect(states).not.toContain('running')
    vi.useRealTimers()
  })

  it('overlapping visibility restarts do not leak a stream', async () => {
    const { calls } = deferredGum()
    const engine = new ScannerEngine({ video, onScan: () => {} })
    const started = engine.start()
    await flush()
    await flush()
    // a second start (e.g. pageshow + visibilitychange) while the first open is pending
    const second = engine.start()
    await flush()
    await flush()
    calls.forEach((c) => c.resolve(null as never))
    await Promise.all([started, second])
    await flush()
    const live = calls.filter((c) => c.made && c.made.track.readyState === 'live')
    expect(live.length).toBe(1)
    engine.stop()
    await flush()
    expect(calls.every((c) => !c.made || c.made.track.readyState === 'ended')).toBe(true)
  })
})
