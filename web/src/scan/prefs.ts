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

const CAM_OK_KEY = 'pn.scan.camok'

/** Remember that the camera ran once on this device (permission was granted), for autostart where permissions.query is missing. */
export function markCameraOk() {
  try {
    localStorage.setItem(CAM_OK_KEY, '1')
  } catch {
    /* ignore */
  }
}

export function clearCameraOk() {
  try {
    localStorage.removeItem(CAM_OK_KEY)
  } catch {
    /* ignore */
  }
}

export function cameraWasOk(): boolean {
  try {
    return localStorage.getItem(CAM_OK_KEY) === '1'
  } catch {
    return false
  }
}

/**
 * Autostart without a tap is allowed when the camera is off (nothing needs a gesture but audio, which waits
 * for the first touch) or the camera permission is known to be granted.
 */
export async function canAutostartCamera(prefs: ScanPrefs): Promise<boolean> {
  if (!prefs.camera) return true
  try {
    const st = await navigator.permissions?.query({ name: 'camera' as PermissionName })
    if (st) return st.state === 'granted'
  } catch {
    /* query unsupported (older Safari): fall through to the remembered flag */
  }
  return cameraWasOk()
}
