import { describe, expect, it } from 'vitest'
import type { ChatEvent } from '@/api/types'
import { createSseParser, readSse } from './sse'

const EVENTS: ChatEvent[] = [
  { type: 'thread', threadId: 't1' },
  { type: 'token', text: 'Héllo — ' },
  { type: 'token', text: 'wörld 🎵' },
  { type: 'suggestions', items: ['More?'] },
  { type: 'done', message: 'Héllo — wörld 🎵' },
]
const WIRE = EVENTS.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')

function collect() {
  const out: ChatEvent[] = []
  return { out, parser: createSseParser((e) => out.push(e)) }
}

describe('createSseParser', () => {
  it('parses whole frames', () => {
    const { out, parser } = collect()
    parser.push(WIRE)
    expect(out).toEqual(EVENTS)
  })

  it('buffers frames split at every possible boundary', () => {
    for (let cut = 1; cut < WIRE.length; cut++) {
      const { out, parser } = collect()
      parser.push(WIRE.slice(0, cut))
      parser.push(WIRE.slice(cut))
      expect(out).toEqual(EVENTS)
    }
  })

  it('handles one character at a time, including a split "\\n\\n"', () => {
    const { out, parser } = collect()
    for (const ch of WIRE) parser.push(ch)
    expect(out).toEqual(EVENTS)
  })

  it('accepts CRLF, comments, "data:" without a space and a final frame with no blank line', () => {
    const { out, parser } = collect()
    parser.push(': keep-alive\r\n\r\ndata:{"type":"token","text":"a"}\r\n\r\n')
    parser.push('data: {"type":"done","message":"a"}')
    expect(out).toEqual([{ type: 'token', text: 'a' }])
    parser.flush()
    expect(out.at(-1)).toEqual({ type: 'done', message: 'a' })
  })

  it('skips malformed and unknown frames', () => {
    const { out, parser } = collect()
    parser.push('data: {not json\n\ndata: {"type":"mystery"}\n\ndata: {"type":"token","text":"ok"}\n\n')
    expect(out).toEqual([{ type: 'token', text: 'ok' }])
  })
})

describe('readSse', () => {
  it('decodes UTF-8 split inside a multi-byte character across chunks', async () => {
    const bytes = new TextEncoder().encode(WIRE)
    const emoji = bytes.indexOf(0xf0) // first byte of 🎵
    const chunks = [bytes.slice(0, emoji + 2), bytes.slice(emoji + 2, emoji + 30), bytes.slice(emoji + 30)]
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const c of chunks) controller.enqueue(c)
        controller.close()
      },
    })
    const out: ChatEvent[] = []
    await readSse(body, (e) => out.push(e))
    expect(out).toEqual(EVENTS)
  })
})
