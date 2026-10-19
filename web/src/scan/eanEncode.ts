// Tiny EAN-13 / EAN-8 module encoder (1 = bar, 0 = space). Used by tests and the e2e fixture
// generator – the app itself only decodes.

const L = ['0001101', '0011001', '0010011', '0111101', '0100011', '0110001', '0101111', '0111011', '0110111', '0001011']
const G = ['0100111', '0110011', '0011011', '0100001', '0011101', '0111001', '0000101', '0010001', '0001001', '0010111']
const R = ['1110010', '1100110', '1101100', '1000010', '1011100', '1001110', '1010000', '1000100', '1001000', '1110100']
const PARITY = ['LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG', 'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL']

export function encodeEan13(digits: string): string {
  if (!/^\d{13}$/.test(digits)) throw new Error('EAN-13 needs 13 digits')
  const par = PARITY[Number(digits[0])]
  let out = '101'
  for (let i = 0; i < 6; i++) out += (par[i] === 'L' ? L : G)[Number(digits[i + 1])]
  out += '01010'
  for (let i = 7; i < 13; i++) out += R[Number(digits[i])]
  return out + '101'
}

export function encodeEan8(digits: string): string {
  if (!/^\d{8}$/.test(digits)) throw new Error('EAN-8 needs 8 digits')
  let out = '101'
  for (let i = 0; i < 4; i++) out += L[Number(digits[i])]
  out += '01010'
  for (let i = 4; i < 8; i++) out += R[Number(digits[i])]
  return out + '101'
}

/** Render modules into a w×h grayscale image (white background, quiet zone, black bars). */
export function renderLuma(modules: string, scale: number, height: number, quietModules = 10, barTop = 0.15) {
  const w = (modules.length + quietModules * 2) * scale
  const luma = new Uint8ClampedArray(w * height).fill(255)
  const y0 = Math.floor(height * barTop)
  const y1 = Math.floor(height * (1 - barTop))
  for (let y = y0; y < y1; y++)
    for (let m = 0; m < modules.length; m++)
      if (modules[m] === '1') for (let s = 0; s < scale; s++) luma[y * w + (quietModules + m) * scale + s] = 0
  return { luma, width: w, height }
}
