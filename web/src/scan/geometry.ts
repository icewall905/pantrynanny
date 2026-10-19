/** Aiming frame as a fraction of the camera box; the decoder only looks inside it. */
export const FRAME = { w: 0.9, h: 0.5 }

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
export function cropRect(videoW: number, videoH: number, boxW: number, boxH: number, frame = FRAME): Rect {
  if (!videoW || !videoH || !boxW || !boxH) return { x: 0, y: 0, w: videoW, h: videoH }
  const scale = Math.max(boxW / videoW, boxH / videoH)
  const visW = boxW / scale
  const visH = boxH / scale
  const w = Math.min(videoW, visW * frame.w)
  const h = Math.min(videoH, visH * frame.h)
  return { x: (videoW - w) / 2, y: (videoH - h) / 2, w, h }
}
