// Hands the current page's address to PantryNanny, which reads the recipe (same scraper as
// "Import from link") and shows it for review. Uses your normal PantryNanny login in the
// browser; the extension itself stores only the server address.
const api = globalThis.browser ?? globalThis.chrome

async function server() {
  const { server } = await api.storage.sync.get('server')
  return typeof server === 'string' && /^https?:\/\//.test(server) ? server.replace(/\/+$/, '') : null
}

async function send(url) {
  if (!url || !/^https?:\/\//.test(url)) return
  const base = await server()
  if (!base) return api.runtime.openOptionsPage()
  await api.tabs.create({ url: `${base}/recipes?import=${encodeURIComponent(url)}` })
}

api.action.onClicked.addListener((tab) => send(tab.url))

api.runtime.onInstalled.addListener(async ({ reason }) => {
  api.contextMenus.create({ id: 'pn-import-page', title: 'Import this recipe to PantryNanny', contexts: ['page'] })
  api.contextMenus.create({ id: 'pn-import-link', title: 'Import linked recipe to PantryNanny', contexts: ['link'] })
  if (reason === 'install' && !(await server())) api.runtime.openOptionsPage()
})

api.contextMenus.onClicked.addListener((info, tab) => send(info.menuItemId === 'pn-import-link' ? info.linkUrl : tab?.url))
