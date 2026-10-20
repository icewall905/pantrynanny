// Audio + haptic feedback with iOS autoplay rules in mind.
export type BeepKind = 'add' | 'remove' | 'unknown' | 'error' | 'dup'

type ACtor = typeof AudioContext
let ctx: AudioContext | null = null
let enabled = true

export function setSoundEnabled(on: boolean) {
  enabled = on
}

const needsResume = () => !!ctx && (ctx.state as string) !== 'running' // WebKit also uses 'interrupted'

let listenersInstalled = false
function installAutoUnlock() {
  if (listenersInstalled || typeof document === 'undefined') return
  listenersInstalled = true
  // WebKit suspends/interrupts the context when the app is backgrounded or audio is interrupted;
  // any later touch (and returning to the page) re-resumes it.
  const again = () => {
    if (!ctx || needsResume()) unlockAudio()
  }
  document.addEventListener('pointerdown', again, { passive: true, capture: true })
  document.addEventListener('touchend', again, { passive: true, capture: true })
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && needsResume()) void ctx?.resume().catch(() => undefined)
  })
}

/** Install the touch/visibility re-unlock listeners without a gesture (auto-resumed sessions). */
export function armAudioUnlock() {
  installAutoUnlock()
}

/** Create/resume the AudioContext. Must run inside a user gesture the first time (Start tap). */
export function unlockAudio(): boolean {
  try {
    const C: ACtor | undefined = window.AudioContext ?? (window as unknown as { webkitAudioContext?: ACtor }).webkitAudioContext
    if (!C) return false
    ctx ??= new C()
    installAutoUnlock()
    if (needsResume()) void ctx.resume().catch(() => undefined)
    // A silent blip fully unlocks iOS Safari.
    const o = ctx.createOscillator()
    const g = ctx.createGain()
    g.gain.value = 0.0001
    o.connect(g).connect(ctx.destination)
    o.start()
    o.stop(ctx.currentTime + 0.02)
    return true
  } catch {
    return false
  }
}

const TONES: Record<BeepKind, [number, number][]> = {
  add: [[880, 0.07], [1320, 0.09]], // rising
  remove: [[660, 0.07], [440, 0.1]], // falling
  unknown: [[300, 0.12], [300, 0.12]], // low double
  error: [[200, 0.25]],
  dup: [[500, 0.06]], // soft neutral tick: seen, but not counted
}

export function beep(kind: BeepKind) {
  if (!enabled || !ctx) return
  try {
    if (needsResume()) void ctx.resume().catch(() => undefined)
    let t = ctx.currentTime
    for (const [freq, dur] of TONES[kind]) {
      const o = ctx.createOscillator()
      const g = ctx.createGain()
      o.type = kind === 'unknown' ? 'square' : 'sine'
      o.frequency.value = freq
      g.gain.setValueAtTime(0.0001, t)
      g.gain.exponentialRampToValueAtTime(0.35, t + 0.01)
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur)
      o.connect(g).connect(ctx.destination)
      o.start(t)
      o.stop(t + dur + 0.02)
      t += dur + 0.02
    }
  } catch {
    /* ignore */
  }
}

/** navigator.vibrate does not exist on iOS; harmless no-op there. */
export function vibrate(pattern: number | number[]) {
  try {
    navigator.vibrate?.(pattern)
  } catch {
    /* ignore */
  }
}
