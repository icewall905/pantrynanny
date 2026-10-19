// Hardware barcode scanners in "keyboard wedge" mode (Bluetooth or USB HID) type the code as a fast
// burst of key presses followed by Enter (or Tab). People type an order of magnitude slower, so a
// burst is recognised by its timing: that is what keeps normal keyboard input from turning into scans.

export interface HidOptions {
  /** longest pause between two characters of one barcode */
  maxGapMs?: number
  /** average pause per character must stay below this */
  maxAvgGapMs?: number
  minLength?: number
  maxLength?: number
  /** the scanner's trigger can bounce: the same code again within this window is ignored */
  repeatMs?: number
}

const DEFAULTS: Required<HidOptions> = { maxGapMs: 80, maxAvgGapMs: 40, minLength: 6, maxLength: 64, repeatMs: 350 }

export class HidBurstDetector {
  private o: Required<HidOptions>
  private buf = ''
  private firstAt = 0
  private lastAt = 0
  private lastCode = ''
  private lastCodeAt = -Infinity

  constructor(o: HidOptions = {}) {
    this.o = { ...DEFAULTS, ...o }
  }

  /**
   * Feed one keydown (`key` as in KeyboardEvent.key). Returns the barcode when this key completed a
   * scanner burst, else null. `consumed` tells the caller to swallow the key (it belongs to a burst).
   */
  feed(key: string, at: number): { code: string | null; consumed: boolean } {
    if (key === 'Enter' || key === 'Tab') {
      const code = this.finish(at)
      return { code, consumed: code !== null }
    }
    if (key.length !== 1) return { code: null, consumed: false } // Shift, arrows, ...
    if (this.buf && at - this.lastAt > this.o.maxGapMs) this.reset()
    if (!this.buf) this.firstAt = at
    this.buf += key
    this.lastAt = at
    if (this.buf.length > this.o.maxLength) this.reset()
    // From the third fast character on, it is almost certainly the scanner talking.
    return { code: null, consumed: this.buf.length >= 3 && this.avgGap() <= this.o.maxAvgGapMs }
  }

  reset() {
    this.buf = ''
  }

  private avgGap() {
    return this.buf.length > 1 ? (this.lastAt - this.firstAt) / (this.buf.length - 1) : Infinity
  }

  private finish(at: number): string | null {
    const code = this.buf
    const fast = code.length >= this.o.minLength && this.avgGap() <= this.o.maxAvgGapMs && at - this.lastAt <= this.o.maxGapMs
    this.reset()
    if (!fast) return null
    if (code === this.lastCode && at - this.lastCodeAt < this.o.repeatMs) return null
    this.lastCode = code
    this.lastCodeAt = at
    return code
  }
}

/** True when the key event goes to a text field: those keys are never treated as scanner input. */
export function isTypingTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false
  if (t.isContentEditable) return true
  const tag = t.tagName
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (tag !== 'INPUT') return false
  const type = (t as HTMLInputElement).type
  return !['checkbox', 'radio', 'button', 'submit', 'range'].includes(type)
}
