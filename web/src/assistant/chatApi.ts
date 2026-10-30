import type { ChatEvent, ChatRequest } from '@/api/types'
import { readSse } from './sse'

type OnEvent = (event: ChatEvent) => void

async function postStream(path: string, body: unknown, onEvent: OnEvent, signal?: AbortSignal): Promise<void> {
  let res: Response
  try {
    res = await fetch(new URL(`/api${path}`, window.location.href), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    onEvent({ type: 'error', detail: 'The assistant is unreachable — is the API running?' })
    return
  }
  if (!res.ok || !res.body) {
    const detail = res.status === 422 ? 'That message could not be sent.' : `The assistant failed (${res.status}).`
    onEvent({ type: 'error', detail })
    return
  }
  await readSse(res.body, onEvent)
}

/** POST /api/chat — streams ChatEvents for one turn. */
export function streamChat(request: ChatRequest, onEvent: OnEvent, signal?: AbortSignal): Promise<void> {
  return postStream('/chat', request, onEvent, signal)
}

/** POST /api/chat/resume — answers a pending interrupt (playlist confirmation). */
export function resumeChat(threadId: string, confirmed: boolean, onEvent: OnEvent, signal?: AbortSignal): Promise<void> {
  return postStream('/chat/resume', { threadId, confirmed }, onEvent, signal)
}
