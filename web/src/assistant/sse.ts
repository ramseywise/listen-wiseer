import type { ChatEvent } from '@/api/types'

// Minimal SSE reader for the chat stream: fetch + ReadableStream (EventSource can't POST).
// Only `data:` lines matter — the API sends one JSON ChatEvent per frame.

const EVENT_TYPES = new Set(['thread', 'token', 'tracks', 'suggestions', 'interrupt', 'done', 'error'])

function toEvent(data: string): ChatEvent | null {
  try {
    const parsed: unknown = JSON.parse(data)
    if (parsed && typeof parsed === 'object' && 'type' in parsed && EVENT_TYPES.has(String(parsed.type))) {
      return parsed as ChatEvent
    }
  } catch {
    // malformed frame — skip it rather than kill the turn
  }
  return null
}

/**
 * Incremental parser: feed it decoded text in arbitrary chunks (a frame, half a frame, three
 * frames…) and it calls `onEvent` once per complete frame.
 */
export function createSseParser(onEvent: (event: ChatEvent) => void) {
  let buffer = ''

  function dispatch(frame: string) {
    const data = frame
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(line.startsWith('data: ') ? 6 : 5))
      .join('\n')
    if (!data) return
    const event = toEvent(data)
    if (event) onEvent(event)
  }

  return {
    push(text: string) {
      buffer += text.replace(/\r\n?/g, '\n')
      let end = buffer.indexOf('\n\n')
      while (end !== -1) {
        dispatch(buffer.slice(0, end))
        buffer = buffer.slice(end + 2)
        end = buffer.indexOf('\n\n')
      }
    },
    /** End of stream: a final frame without the trailing blank line still counts. */
    flush() {
      if (buffer.trim()) dispatch(buffer)
      buffer = ''
    },
  }
}

/** Read an SSE response body to the end, decoding UTF-8 across chunk boundaries. */
export async function readSse(body: ReadableStream<Uint8Array>, onEvent: (event: ChatEvent) => void): Promise<void> {
  const parser = createSseParser(onEvent)
  const reader = body.getReader()
  const decoder = new TextDecoder()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      parser.push(decoder.decode(value, { stream: true }))
    }
    parser.push(decoder.decode())
    parser.flush()
  } finally {
    reader.releaseLock()
  }
}
