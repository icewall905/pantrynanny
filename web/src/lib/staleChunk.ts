// After a deploy, a tab still running the previous build may request code-split chunks that no
// longer exist ("error loading dynamically imported module"). Reload once to pick up the new build.
const KEY = 'pn.staleChunkReload'

export function isStaleChunkError(e: unknown): boolean {
  const msg = e instanceof Error ? e.message : String(e ?? '')
  return /dynamically imported module|Importing a module script failed|Failed to fetch dynamically imported|error loading dynamically imported/i.test(
    msg,
  )
}

/** Reload at most once per minute so a genuinely broken deploy can't loop forever. */
export function reloadForStaleChunk(): boolean {
  try {
    const last = Number(sessionStorage.getItem(KEY) ?? 0)
    if (Date.now() - last < 60_000) return false
    sessionStorage.setItem(KEY, String(Date.now()))
  } catch {
    // storage unavailable: guard with a URL marker instead, so a broken deploy can't loop
    const url = new URL(window.location.href)
    if (url.searchParams.has('_r')) return false
    url.searchParams.set('_r', '1')
    window.location.replace(url.toString())
    return true
  }
  window.location.reload()
  return true
}

export function installStaleChunkHandler() {
  window.addEventListener('vite:preloadError', (ev) => {
    if (reloadForStaleChunk()) ev.preventDefault()
  })
  window.addEventListener('unhandledrejection', (ev) => {
    if (isStaleChunkError(ev.reason)) reloadForStaleChunk()
  })
}
