const BASE = ''

async function req(path, options = {}) {
  const r = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!r.ok) {
    let detail = `${r.status}`
    try { detail = (await r.json()).detail || detail } catch {}
    throw new Error(detail)
  }
  return r.json()
}

export const api = {
  config: () => req('/api/config'),
  project: () => req('/api/project'),
  generate: () => req('/api/project/generate', { method: 'POST' }),
  rollback: (tick) => req('/api/project/rollback', { method: 'POST', body: JSON.stringify({ tick }) }),
  reset: () => req('/api/project/reset', { method: 'POST' }),
}
