import { describe, expect, it } from 'vitest'
import { isStaleChunkError } from './staleChunk'

describe('isStaleChunkError', () => {
  it('recognises browser chunk-load failures', () => {
    expect(isStaleChunkError(new TypeError('error loading dynamically imported module: https://x/assets/A.js'))).toBe(true)
    expect(isStaleChunkError(new TypeError('Failed to fetch dynamically imported module: https://x/a.js'))).toBe(true)
    expect(isStaleChunkError(new TypeError('Importing a module script failed.'))).toBe(true)
  })
  it('ignores other errors', () => {
    expect(isStaleChunkError(new Error('Network down'))).toBe(false)
    expect(isStaleChunkError(undefined)).toBe(false)
  })
})
