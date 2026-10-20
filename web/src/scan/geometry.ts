/**
 * Aiming frame as a fraction of the camera box; the decoder only looks inside it. `square`: both
 * dimensions use the same pixel size (the smaller of the two fractions), so a barcode held at any angle
 * (rotated up to 90°) fits inside the decoded crop.
 */
export interface AimFrame {
  w: number
  h: number
  square?: boolean
}
export const FRAME: AimFrame = { w: 0.9, h: 0.9, square: true }

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

/**
 * Source rectangle (video pixels) matching the aiming frame, given the video is displayed with
 * `object-fit: cover` inside a box of boxW × boxH.
 */
export function cropRect(videoW: number, videoH: number, boxW: number, boxH: number, frame: AimFrame = FRAME): Rect {
  if (!videoW || !videoH || !boxW || !boxH) return { x: 0, y: 0, w: videoW, h: videoH }
  const scale = Math.max(boxW / videoW, boxH / videoH)
  const visW = boxW / scale
  const visH = boxH / scale
  let w = Math.min(videoW, visW * frame.w)
  let h = Math.min(videoH, visH * frame.h)
  if (frame.square) w = h = Math.min(w, h)
  return { x: (videoW - w) / 2, y: (videoH - h) / 2, w, h }
}
