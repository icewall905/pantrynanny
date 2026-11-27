const api = globalThis.browser ?? globalThis.chrome
const $ = (id) => document.getElementById(id)
const say = (text, error = false) => {
  $('msg').textContent = text
  $('msg').className = error ? 'err' : ''
}

async function show() {
  const { server, token, who } = await api.storage.local.get(['server', 'token', 'who'])
  if (server) $('server').value = server
  $('in').hidden = !token
  $('f').hidden = !!token
  $('where').textContent = server || ''
  $('who').textContent = who || ''
}

$('f').addEventListener('submit', (e) => {
  e.preventDefault()
  say('')
  let origin
  try {
    origin = new URL($('server').value.trim()).origin
  } catch {
    return say('That is not a valid address.', true)
  }
  // must be asked straight from the click: lets the extension talk to this PantryNanny only
  api.permissions.request({ origins: [`${origin}/*`] }).then(
    (ok) => (ok ? login(origin) : say('The extension needs permission to reach PantryNanny.', true)),
    (err) => say(String(err), true),
  )
})

async function login(origin) {
  say('Logging in…')
  let r
  try {
    r = await fetch(`${origin}/api/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: $('user').value.trim(),
        password: $('pass').value,
        device_name: 'Browser extension',
        platform: 'browser-extension',
      }),
    })
  } catch {
    return say(`Could not reach ${origin}.`, true)
  }
  const body = await r.json().catch(() => ({}))
  if (!r.ok) return say(body.detail || `Login failed (${r.status}).`, true)
  $('pass').value = ''
  const who = body.me?.user?.display_name || body.me?.user?.username || $('user').value.trim()
  await api.storage.local.set({ server: origin, token: body.token, who })
  say('Logged in. Open a recipe page and click the PantryNanny button.')
  show()
}

$('logout').addEventListener('click', async () => {
  const { server, token } = await api.storage.local.get(['server', 'token'])
  if (server && token) {
    await fetch(`${server}/api/auth/logout`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }).catch(() => {})
  }
  await api.storage.local.remove(['token', 'who'])
  say('Logged out.')
  show()
})

show()
