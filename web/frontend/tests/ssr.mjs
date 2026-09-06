import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { after, before, test } from 'node:test'

const root = fileURLToPath(new URL('..', import.meta.url))
const original = JSON.parse(
  await readFile(new URL('./fixtures/statistics.json', import.meta.url)),
)
const release = JSON.parse(
  await readFile(new URL('./fixtures/statistics-0.4.0.json', import.meta.url)),
)
let current = structuredClone(original),
  unavailable = false,
  child,
  base,
  api
const requests = []
const page = (items) => ({ items, total: items.length, offset: 0, limit: 100 })
before(async () => {
  api = createServer((req, res) => {
    requests.push({ path: req.url, accept: req.headers.accept })
    res.setHeader('Content-Type', 'application/json')
    res.setHeader('Cache-Control', 'no-cache')
    if (unavailable) {
      res.writeHead(503)
      res.end('{"detail":"Registry database unavailable"}')
      return
    }
    const path = new URL(req.url, 'http://localhost').pathname
    let value
    if (path === '/api/v1/modules') value = page([current])
    else if (path === '/api/v1/modules/statistics') value = current
    else if (path === '/api/v1/modules/statistics/versions')
      value = page([release])
    else if (path.startsWith('/api/v1/modules/statistics/versions/'))
      value = {
        ...release,
        version: current.channels.stable.version,
        artifact: {
          ...release.artifact,
          sha256: current.channels.stable.sha256,
        },
      }
    else if (path === '/api/v1/publishers')
      value = page([{ ...current.publisher, module_count: 1 }])
    else if (path === '/api/v1/publishers/oklabflensburg')
      value = {
        ...current.publisher,
        module_count: 1,
        modules: page([current]),
      }
    else if (path === '/api/v1/search')
      value = { ...page([current]), query: 'statistics' }
    else {
      res.writeHead(404)
      value = { detail: 'Module not found' }
    }
    res.end(JSON.stringify(value))
  })
  await new Promise((resolve) => api.listen(0, '127.0.0.1', resolve))
  const portReservation = createServer()
  await new Promise((resolve) =>
    portReservation.listen(0, '127.0.0.1', resolve),
  )
  const port = portReservation.address().port
  await new Promise((resolve) => portReservation.close(resolve))
  base = `http://127.0.0.1:${port}`
  child = spawn(process.execPath, ['.output/server/index.mjs'], {
    cwd: root,
    env: {
      ...process.env,
      PORT: String(port),
      HOST: '127.0.0.1',
      NUXT_API_BASE_INTERNAL: `http://127.0.0.1:${api.address().port}/api`,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let log = ''
  child.stderr.on('data', (data) => {
    log += data
  })
  child.stdout.on('data', () => {})
  for (let n = 0; n < 100; n++) {
    if (child.exitCode !== null) throw new Error(log)
    try {
      if ((await fetch(`${base}/logo.svg`)).ok) return
    } catch {
      /* Starting. */
    }
    await delay(100)
  }
  throw new Error(`SSR server did not start: ${log}`)
})
after(async () => {
  child?.kill()
  if (api) await new Promise((resolve) => api.close(resolve))
})
test('built detail SSR contains DB DTO, stable version, SHA, license, SEO and immutable artifact', async () => {
  const response = await fetch(`${base}/packages/statistics`)
  assert.equal(response.status, 200)
  const html = await response.text()
  for (const value of [
    'Statistics – Open City Planner Package Hub',
    '0.4.0',
    original.description,
    original.license,
    release.artifact.sha256,
    release.artifact.url,
    'rel="canonical"',
    'property="og:title"',
    'module-navigation',
    'metadata-rail',
  ])
    assert.ok(html.includes(value), value)
  assert.ok(
    requests.every(
      (req) => req.accept === 'application/vnd.ocp.registry.v2+json',
    ),
  )
})
test('search and publisher SSR negotiate v2', async () => {
  for (const path of [
    '/packages?q=statistics',
    '/publishers',
    '/publishers/oklabflensburg',
  ]) {
    const response = await fetch(base + path)
    assert.equal(response.status, 200)
    assert.ok((await response.text()).includes('OK Lab Flensburg'))
  }
  assert.ok(
    requests
      .filter((req) => /search|publishers/.test(req.path))
      .every((req) => req.accept === 'application/vnd.ocp.registry.v2+json'),
  )
})
test('an API pointer change is reflected by the same running build on the next SSR request', async () => {
  current = {
    ...original,
    stable_version: '0.5.0',
    channels: { stable: { version: '0.5.0', sha256: 'a'.repeat(64) } },
  }
  const html = await (await fetch(`${base}/packages/statistics`)).text()
  assert.match(html, /class="stable-number">0\.5\.0/)
  assert.ok(html.includes('a'.repeat(64)))
  current = structuredClone(original)
})
test('unknown module is HTTP 404', async () => {
  const response = await fetch(`${base}/packages/not-published`)
  assert.equal(response.status, 404)
  assert.ok((await response.text()).includes('nicht gefunden'))
})
test('database outage is HTTP 503, never a fabricated module or false 404', async () => {
  unavailable = true
  const response = await fetch(`${base}/packages/statistics`)
  assert.equal(response.status, 503)
  assert.ok((await response.text()).includes('Registry API nicht verfügbar'))
  unavailable = false
})
