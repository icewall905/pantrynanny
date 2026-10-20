import { describe, expect, it } from 'vitest'
import { buildScanLink, parseScanParams, swapToScanManifest } from './link'

describe('parseScanParams', () => {
  it('defaults', () => {
    expect(parseScanParams('')).toEqual({ autostart: false, mode: 'add', camera: null })
  })
  it('reads all params', () => {
    expect(parseScanParams('?autostart=1&mode=remove&camera=off')).toEqual({ autostart: true, mode: 'remove', camera: 'off' })
    expect(parseScanParams('?autostart=0&mode=bogus&camera=on')).toEqual({ autostart: false, mode: 'add', camera: 'on' })
  })
})

describe('buildScanLink', () => {
  it('builds the variants', () => {
    expect(buildScanLink('https://pantry.example.com')).toBe('https://pantry.example.com/scan?autostart=1')
    expect(buildScanLink('https://pantry.example.com/', { mode: 'remove' })).toBe('https://pantry.example.com/scan?autostart=1&mode=remove')
    expect(buildScanLink('https://pantry.example.com', { cameraOff: true })).toBe('https://pantry.example.com/scan?autostart=1&camera=off')
  })
  it('round-trips through the parser', () => {
    const u = new URL(buildScanLink('https://pantry.example.com', { mode: 'remove', cameraOff: true }))
    expect(parseScanParams(u.search)).toEqual({ autostart: true, mode: 'remove', camera: 'off' })
  })
})

describe('swapToScanManifest', () => {
  it('swaps and restores the manifest link and the iOS title', () => {
    document.head.innerHTML =
      '<link rel="manifest" href="/manifest.webmanifest"><meta name="apple-mobile-web-app-title" content="PantryNanny">'
    const restore = swapToScanManifest()
    expect(document.querySelector('link[rel="manifest"]')?.getAttribute('href')).toBe('/manifest-scan.webmanifest')
    expect(document.querySelector('meta[name="apple-mobile-web-app-title"]')?.getAttribute('content')).toBe('Scan')
    restore()
    expect(document.querySelector('link[rel="manifest"]')?.getAttribute('href')).toBe('/manifest.webmanifest')
    expect(document.querySelector('meta[name="apple-mobile-web-app-title"]')?.getAttribute('content')).toBe('PantryNanny')
  })
})
