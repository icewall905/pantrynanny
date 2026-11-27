const api = globalThis.browser ?? globalThis.chrome
const input = document.getElementById('server')
const msg = document.getElementById('msg')
api.storage.sync.get('server').then(({ server }) => {
  if (server) input.value = server
})
document.getElementById('f').addEventListener('submit', async (e) => {
  e.preventDefault()
  let v = input.value.trim().replace(/\/+$/, '')
  try {
    v = new URL(v).origin
  } catch {
    msg.textContent = 'Not a valid address'
    return
  }
  await api.storage.sync.set({ server: v })
  input.value = v
  msg.textContent = 'Saved'
})
