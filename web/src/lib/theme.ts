// Colour theme. Dark is the default (index.css styles :root dark unless <html data-theme="light">),
// so a first visit never flashes white. The choice is per device, like the language.

export type Theme = 'dark' | 'light'
const KEY = 'pn-theme'

export function getTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

export function applyTheme(theme: Theme = getTheme()): void {
  document.documentElement.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#131210' : '#2f7d4f')
}

export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    /* private mode: still applies for this visit */
  }
  applyTheme(theme)
}
