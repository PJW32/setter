import type { AgentEvent, SessionView } from './types'

const SESSION_KEY = 'saeteo.session'

async function check(response: Response): Promise<Response> {
  if (response.ok) return response
  let detail = `요청 실패 (${response.status})`
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') detail = body.detail
  } catch { /* JSON이 아닌 프록시 오류도 HTTP 상태로 안내한다. */ }
  throw new Error(detail)
}

export async function createSession(): Promise<SessionView> {
  const session: SessionView = await (await check(await fetch('/api/sessions', { method: 'POST' }))).json()
  localStorage.setItem(SESSION_KEY, session.session_id)
  return session
}

export async function restoreSession(): Promise<SessionView> {
  const id = localStorage.getItem(SESSION_KEY)
  if (!id) return createSession()
  const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`)
  if (response.status === 404) return createSession()
  return (await check(response)).json()
}

/** POST SSE: 청크 경계와 UTF-8 멀티바이트 문자가 이벤트 경계와 같다고 가정하지 않는다. */
export async function sendMessage(id: string, text: string, onEvent: (event: AgentEvent) => void): Promise<void> {
  const response = await check(await fetch(`/api/sessions/${encodeURIComponent(id)}/messages`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
  }))
  if (!response.body) throw new Error('서버 응답 스트림이 없습니다')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed = false
  const dispatch = (chunk: string) => {
    const data = chunk.split(/\r?\n/).filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).replace(/^ /, '')).join('\n')
    if (!data) return
    const event: AgentEvent = JSON.parse(data)
    onEvent(event)
    if (event.type === 'done') completed = true
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let separator: RegExpExecArray | null
      while ((separator = /\r?\n\r?\n/.exec(buffer))) {
        dispatch(buffer.slice(0, separator.index))
        buffer = buffer.slice(separator.index + separator[0].length)
      }
      if (done) break
    }
    if (buffer.trim()) dispatch(buffer)
    if (!completed) throw new Error('응답이 완료되기 전에 연결이 종료됐어요. 다시 시도해 주세요.')
  } finally {
    reader.releaseLock()
  }
}
