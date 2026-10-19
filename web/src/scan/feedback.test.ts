import { describe, expect, it, vi } from 'vitest'
import { beep, setSoundEnabled, unlockAudio } from './feedback'

describe('audio state handling', () => {
  it("resumes a WebKit 'interrupted' context and on later touches", () => {
    const resume = vi.fn(() => Promise.resolve())
    class FakeCtx {
      state = 'interrupted'
      currentTime = 0
      destination = {}
      resume = resume
      createOscillator = () => ({ connect: () => ({ connect: () => ({}) }), start() {}, stop() {}, frequency: {}, type: '' })
      createGain = () => ({ gain: { value: 0, setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect: () => ({}) })
    }
    vi.stubGlobal('AudioContext', FakeCtx)
    window.AudioContext = FakeCtx as never
    expect(unlockAudio()).toBe(true)
    expect(resume).toHaveBeenCalled()
    resume.mockClear()
    setSoundEnabled(true)
    beep('add')
    expect(resume).toHaveBeenCalled() // state !== 'running' → resume before playing
    resume.mockClear()
    document.dispatchEvent(new Event('pointerdown'))
    expect(resume).toHaveBeenCalled()
  })
})
