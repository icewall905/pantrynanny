// Camera access: rear camera by default (front on request), continuous focus, torch where available.

export type Facing = 'environment' | 'user'

/** Device labels that identify each side (several languages; labels are only known after permission). */
const LABEL: Record<Facing, RegExp> = {
  environment: /back|rear|bak|environment|hinten|arrière/i,
  user: /front|user|forside|facetime|vorne|avant/i,
}

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
  /** Which camera open() asks for. */
  facing: Facing = 'environment'
  /** More than one camera present (known after the first successful open). */
  canSwitch = false
  onEnded: (() => void) | null = null

  async open(video: HTMLVideoElement): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new CameraError(window.isSecureContext ? 'other' : 'insecure', 'getUserMedia unavailable')
    }
    this.close() // bumps gen: any older pending open() will discard its stream
    const my = this.gen
    const live = () => my === this.gen
    const want = this.facing
    let stream = await this.request({
      video: { facingMode: { ideal: want }, width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    })
    if (!live()) {
      stopStream(stream)
      throw new OpenSuperseded()
    }
    // Make sure we really got the requested side; pick a camera by label if not.
    const fm = stream.getVideoTracks()[0]?.getSettings().facingMode
    let devices: MediaDeviceInfo[] = []
    try {
      devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput')
    } catch {
      /* ignore */
    }
    this.canSwitch = devices.length > 1
    if (fm && fm !== want) {
      try {
        const match = devices.find((d) => LABEL[want].test(d.label))
        if (match && live()) {
          stopStream(stream)
          stream = await this.request({
            video: { deviceId: { exact: match.deviceId }, width: { ideal: 1280 }, height: { ideal: 720 } },
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
