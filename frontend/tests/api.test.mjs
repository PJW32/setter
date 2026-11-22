import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { createSession, restoreSession, sendMessage } from '../src/lib/api.ts'

const originalFetch = globalThis.fetch
const originalStorage = globalThis.localStorage
afterEach(() => {
  globalThis.fetch = originalFetch
  globalThis.localStorage = originalStorage
})

function storage(id = null) {
  const data = new Map(id ? [['saeteo.session', id]] : [])
  globalThis.localStorage = { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, v) }
  return data
}

test('session creation saves the server session ID', async () => {
  const data = storage()
  globalThis.fetch = async () => Response.json({ session_id: 'new' })
  assert.equal((await createSession()).session_id, 'new')
  assert.equal(data.get('saeteo.session'), 'new')
})

test('expired session is replaced, server failures are preserved', async () => {
  storage('expired')
  const requests = []
  globalThis.fetch = async (url) => {
    requests.push(url)
    return url.endsWith('/expired') ? new Response('', { status: 404 }) : Response.json({ session_id: 'new' })
  }
  assert.equal((await restoreSession()).session_id, 'new')
  assert.equal(requests.length, 2)
  globalThis.fetch = async () => Response.json({ detail: '일시 장애' }, { status: 503 })
  await assert.rejects(restoreSession, /일시 장애/)
})

test('SSE decodes Korean split across bytes and CRLF delimiters', async () => {
  const bytes = new TextEncoder().encode('event: message\r\ndata: {"type":"message","text":"동네"}\r\n\r\nevent: done\ndata: {"type":"done"}\n\n')
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
      controller.close()
    },
  }))
  const events = []
  await sendMessage('s', '추천', (ev) => events.push(ev))
  assert.deepEqual(events.map((ev) => ev.type), ['message', 'done'])
  assert.equal(events[0].text, '동네')
})

test('SSE reports a connection closed without done', async () => {
  globalThis.fetch = async () => new Response('data: {"type":"log"}\n\n')
  await assert.rejects(() => sendMessage('s', '추천', () => {}), /연결이 종료/)
})
