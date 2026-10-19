// Screen Wake Lock with re-acquire on visibility change.
export type WakeState = 'unsupported' | 'active' | 'failed' | 'idle'

interface Sentinel extends EventTarget {
  release(): Promise<void>
  released: boolean
}

export class WakeLock {
  private sentinel: Sentinel | null = null
  private wanted = false
  state: WakeState = 'idle'
  private onChange?: (s: WakeState) => void
  constructor(onChange?: (s: WakeState) => void) {
    this.onChange = onChange
  }

  private set(s: WakeState) {
    this.state = s
    this.onChange?.(s)
  }

  async acquire() {
    this.wanted = true
    document.addEventListener('visibilitychange', this.onVis)
    await this.request()
  }

  private async request() {
    const wl = (navigator as unknown as { wakeLock?: { request(t: 'screen'): Promise<Sentinel> } }).wakeLock
    if (!wl) return this.set('unsupported')
    try {
      this.sentinel = await wl.request('screen')
      this.sentinel.addEventListener('release', () => {
        if (this.wanted && document.visibilityState === 'visible') void this.request()
        else if (this.state === 'active') this.set('idle')
      })
      this.set('active')
    } catch {
      this.set('failed')
    }
  }

  private onVis = () => {
    if (this.wanted && document.visibilityState === 'visible' && (!this.sentinel || this.sentinel.released)) void this.request()
  }

  async release() {
    this.wanted = false
    document.removeEventListener('visibilitychange', this.onVis)
    try {
      await this.sentinel?.release()
    } catch {
      /* ignore */
    }
    this.sentinel = null
    this.set('idle')
  }
}
