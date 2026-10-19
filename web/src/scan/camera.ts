// Camera access: rear camera, continuous focus, torch where available.

export type CameraErrorKind = 'denied' | 'notfound' | 'insecure' | 'busy' | 'other'

export class CameraError extends Error {
  kind: CameraErrorKind
  constructor(kind: CameraErrorKind, message: string) {
    super(message)
    this.kind = kind
  }
}

interface ExtCaps extends MediaTrackCapabilities {
  torch?: boolean
  focusMode?: string[]
}

/** open() was superseded by close()/another open() while awaiting the browser. */
export class OpenSuperseded extends Error {
  constructor() {
    super('camera open superseded')
  }
}

const stopStream = (s: MediaStream | null | undefined) => s?.getTracks().forEach((t) => t.stop())

export class Camera {
  private gen = 0
  stream: MediaStream | null = null
  track: MediaStreamTrack | null = null
  torchSupported = false
  focusContinuous = false
  onEnded: (() => void) | null = null

  async open(video: HTMLVideoElement): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new CameraError(window.isSecureContext ? 'other' : 'insecure', 'getUserMedia unavailable')
    }
    this.close() // bumps gen: any older pending open() will discard its stream
    const my = this.gen
    const live = () => my === this.gen
    let stream = await this.request({
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    })
    if (!live()) {
      stopStream(stream)
      throw new OpenSuperseded()
    }
    // Make sure we really got a rear camera; pick one by label if not.
    const fm = stream.getVideoTracks()[0]?.getSettings().facingMode
    if (fm && fm !== 'environment') {
      try {
        const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput')
        const back = devices.find((d) => /back|rear|bak|environment|hinten|arrière/i.test(d.label))
        if (back && live()) {
          stopStream(stream)
          stream = await this.request({
            video: { deviceId: { exact: back.deviceId }, width: { ideal: 1280 }, height: { ideal: 720 } },
            audio: false,
          })
        }
      } catch {
        /* keep the first stream */
      }
      if (!live()) {
        stopStream(stream)
        throw new OpenSuperseded()
      }
    }
    this.stream = stream
    this.track = stream.getVideoTracks()[0] ?? null
    this.track?.addEventListener('ended', () => {
      if (live()) this.onEnded?.()
    })
    await this.tune()
    if (!live()) {
      stopStream(stream)
      throw new OpenSuperseded()
    }
    video.muted = true
    video.setAttribute('playsinline', 'true')
    video.srcObject = stream
    await video.play().catch(() => undefined)
    if (!live()) {
      stopStream(stream)
      throw new OpenSuperseded()
    }
  }

  private async request(c: MediaStreamConstraints): Promise<MediaStream> {
    try {
      return await navigator.mediaDevices.getUserMedia(c)
    } catch (e) {
      const name = (e as DOMException)?.name
      if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError')
        throw new CameraError('denied', String(e))
      if (name === 'NotFoundError' || name === 'OverconstrainedError') throw new CameraError('notfound', String(e))
      if (name === 'NotReadableError' || name === 'AbortError') throw new CameraError('busy', String(e))
      throw new CameraError('other', String(e))
    }
  }

  private async tune() {
    const t = this.track
    if (!t) return
    let caps: ExtCaps = {}
    try {
      caps = (t.getCapabilities?.() ?? {}) as ExtCaps
    } catch {
      /* ignore */
    }
    this.torchSupported = !!caps.torch
    this.focusContinuous = !!caps.focusMode?.includes('continuous')
    if (this.focusContinuous) {
      try {
        await t.applyConstraints({ advanced: [{ focusMode: 'continuous' } as MediaTrackConstraintSet] })
      } catch {
        /* ignore */
      }
    }
  }

  async setTorch(on: boolean): Promise<boolean> {
    if (!this.track || !this.torchSupported) return false
    try {
      await this.track.applyConstraints({ advanced: [{ torch: on } as MediaTrackConstraintSet] })
      return true
    } catch {
      return false
    }
  }

  get alive() {
    return !!this.track && this.track.readyState === 'live'
  }

  close() {
    this.gen++
    this.onEnded = null
    this.stream?.getTracks().forEach((t) => t.stop())
    this.stream = null
    this.track = null
  }
}
