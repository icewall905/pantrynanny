// Direct scanner link: /scan?autostart=1[&mode=add|remove][&camera=off|on]
import type { ScanMode } from './mode'

export interface ScanParams {
  /** start scanning without the Start tap when the browser allows it */
  autostart: boolean
  mode: ScanMode
  /** 'off' = hand-scanner-only station, 'on' = force camera on, null = keep the device setting */
  camera: 'off' | 'on' | null
}

export function parseScanParams(search: string): ScanParams {
  const q = new URLSearchParams(search)
  const camera = q.get('camera')
  return {
    autostart: q.get('autostart') === '1',
    mode: q.get('mode') === 'remove' ? 'remove' : 'add',
    camera: camera === 'off' ? 'off' : camera === 'on' ? 'on' : null,
  }
}

export interface ScanLinkVariant {
  mode?: ScanMode
  cameraOff?: boolean
}

/** Full URL for a direct scanner link, e.g. https://pantry.example.com/scan?autostart=1 */
export function buildScanLink(origin: string, v: ScanLinkVariant = {}): string {
  let s = `${origin.replace(/\/+$/, '')}/scan?autostart=1`
  if (v.mode === 'remove') s += '&mode=remove'
  if (v.cameraOff) s += '&camera=off'
  return s
}

export const SCAN_MANIFEST_HREF = '/manifest-scan.webmanifest'

/**
 * Point the page at the scanner manifest (so "Add to Home Screen" from /scan opens the scanner) and set the
 * iOS home-screen title to "Scan". Returns a function that restores the normal manifest and title.
 */
export function swapToScanManifest(doc: Document = document): () => void {
  const link = doc.querySelector<HTMLLinkElement>('link[rel="manifest"]')
  const title = doc.querySelector<HTMLMetaElement>('meta[name="apple-mobile-web-app-title"]')
  const prevHref = link?.getAttribute('href') ?? null
  const prevTitle = title?.getAttribute('content') ?? null
  link?.setAttribute('href', SCAN_MANIFEST_HREF)
  title?.setAttribute('content', 'Scan')
  return () => {
    if (link && prevHref !== null) link.setAttribute('href', prevHref)
    if (title && prevTitle !== null) title.setAttribute('content', prevTitle)
  }
}
