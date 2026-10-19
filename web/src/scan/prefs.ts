// Per-device scanner preferences (Settings › Scanner). Device-local on purpose: a wall iPad with a
// Bluetooth scanner and a phone in someone's pocket want different set-ups.

export interface ScanPrefs {
  /** accept input from a Bluetooth/USB barcode scanner in keyboard mode */
  hid: boolean
  /** use the camera; off = hardware scanner only (saves battery, no camera prompt) */
  camera: boolean
  /** show the +N / −N buttons after a scan */
  quantity: boolean
}

const KEY = 'pn.scan.prefs'
export const DEFAULT_PREFS: ScanPrefs = { hid: true, camera: true, quantity: true }

export function loadScanPrefs(): ScanPrefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(KEY) ?? '{}') }
  } catch {
    return { ...DEFAULT_PREFS }
  }
}

export function saveScanPrefs(p: ScanPrefs) {
  try {
    localStorage.setItem(KEY, JSON.stringify(p))
  } catch {
    /* ignore */
  }
}
