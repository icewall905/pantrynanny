// Renders the PantryNanny icon set from inline SVG using Playwright's Chromium.
// Usage: node scripts/gen-icons.mjs   (writes web/public/*.png and favicon.svg)
import { chromium } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const pub = join(dirname(fileURLToPath(import.meta.url)), '..', 'public')

// content drawn in a 512 box, centred inside the maskable safe zone (inner 80%).
const glyph = `
  <g transform="translate(256 262) scale(0.92) translate(-256 -256)">
    <rect x="168" y="96" width="176" height="52" rx="16" fill="#fff"/>
    <rect x="148" y="132" width="216" height="288" rx="56" fill="#fff"/>
    <g fill="#23603c">
      <rect x="190" y="230" width="14" height="110" rx="3"/><rect x="214" y="230" width="7" height="110" rx="2"/>
      <rect x="231" y="230" width="18" height="110" rx="3"/><rect x="259" y="230" width="8" height="110" rx="2"/>
      <rect x="277" y="230" width="14" height="110" rx="3"/><rect x="301" y="230" width="9" height="110" rx="2"/>
    </g>
    <path d="M256 214 C 256 168 288 150 332 150 C 332 196 302 214 256 214 Z" fill="#f4b740"/>
    <path d="M256 214 C 276 190 300 172 322 160" stroke="#b9810f" stroke-width="5" fill="none" stroke-linecap="round"/>
  </g>`
const defs = `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3bb06e"/><stop offset="1" stop-color="#23603c"/></linearGradient></defs>`
const svg = (round) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">${defs}<rect width="512" height="512" ${round ? 'rx="112"' : ''} fill="url(#g)"/>${glyph}</svg>`

writeFileSync(join(pub, 'favicon.svg'), svg(true))

const browser = await chromium.launch({ executablePath: process.env.PN_CHROMIUM || undefined })
const page = await browser.newPage()
async function png(name, size, round) {
  await page.setViewportSize({ width: size, height: size })
  await page.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:${size}px;height:${size}px}</style>${svg(round)}`)
  await page.screenshot({ path: join(pub, name), omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } })
}
await png('icon-192.png', 192, true)
await png('icon-512.png', 512, true)
await png('icon-maskable-512.png', 512, false) // full-bleed, OS applies the mask
await png('apple-touch-icon.png', 180, false) // iOS rounds corners itself
await browser.close()
console.log('icons written to', pub)
