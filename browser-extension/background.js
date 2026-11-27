// Saves the recipe on the current page to PantryNanny. The recipe's structured data is read
// from the page as the browser shows it (works on sites that block servers), then sent to
// POST /api/recipes/import/save with this browser's own login token. A page that is already
// saved opens that recipe instead of saving it twice.
const api = globalThis.browser ?? globalThis.chrome
const ICON = 'icon.png'

async function settings() {
  const { server, token } = await api.storage.local.get(['server', 'token'])
  return { server: typeof server === 'string' ? server : null, token: typeof token === 'string' ? token : null }
}

function notify(title, message) {
  api.notifications.create({ type: 'basic', iconUrl: ICON, title, message: message || '' })
}

async function badge(text, color) {
  await api.action.setBadgeText({ text })
  if (color) await api.action.setBadgeBackgroundColor({ color })
}

// Runs inside the page: only the recipe data blocks, not the whole page.
function readRecipeData() {
  return Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
    .map((s) => `<script type="application/ld+json">${s.textContent}</script>`)
    .join('\n')
}

async function pageData(tabId) {
  try {
    const [res] = await api.scripting.executeScript({ target: { tabId }, func: readRecipeData })
    return typeof res?.result === 'string' && res.result ? res.result.slice(0, 1_900_000) : null
  } catch {
    return null // e.g. a browser page; the server then reads the address itself
  }
}

async function save(url, tabId) {
  if (!url || !/^https?:\/\//.test(url)) {
    notify('PantryNanny', 'Open a recipe web page first.')
    return
  }
  const { server, token } = await settings()
  if (!server || !token) {
    notify('PantryNanny', 'Log in to PantryNanny in the extension settings first.')
    return api.runtime.openOptionsPage()
  }
  await badge('…', '#64748b')
  const html = tabId != null ? await pageData(tabId) : null
  let r
  try {
    r = await fetch(`${server}/api/recipes/import/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(html ? { url, html } : { url }),
    })
  } catch {
    await badge('!', '#dc2626')
    return notify('PantryNanny not reachable', `Could not reach ${server}.`)
  }
  const body = await r.json().catch(() => ({}))
  if (r.status === 401) {
    await api.storage.local.remove('token')
    await badge('!', '#dc2626')
    notify('PantryNanny', 'Your login has expired. Log in again.')
    return api.runtime.openOptionsPage()
  }
  if (!r.ok) {
    await badge('!', '#dc2626')
    return notify('Recipe not saved', body.detail || `PantryNanny answered ${r.status}.`)
  }
  await badge('✓', '#16a34a')
  setTimeout(() => badge(''), 4000)
  notify(body.created ? 'Recipe saved' : 'Already saved', body.recipe.title)
  await api.tabs.create({ url: `${server}/recipes/${body.recipe.id}` })
}

api.action.onClicked.addListener((tab) => save(tab.url, tab.id))

api.runtime.onInstalled.addListener(async ({ reason }) => {
  api.contextMenus.removeAll(() => {
    api.contextMenus.create({ id: 'pn-page', title: 'Save this recipe to PantryNanny', contexts: ['page'] })
    api.contextMenus.create({ id: 'pn-link', title: 'Save linked recipe to PantryNanny', contexts: ['link'] })
  })
  if (reason === 'install') api.runtime.openOptionsPage()
})

api.contextMenus.onClicked.addListener((info, tab) =>
  info.menuItemId === 'pn-link' ? save(info.linkUrl, null) : save(info.pageUrl || tab?.url, tab?.id),
)
