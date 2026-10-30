import { HttpResponse, http } from 'msw'
import type { ChatEvent, ChatRequest, ChatTrack, Playable, Song } from '@/api/types'
import { songs } from './fixtures'

// Mock /api/chat + /api/chat/resume (SSE) and /api/playable for `npm run dev:mock` and tests.
// "save …" asks for playlist confirmation; anything else streams a reply with track cards.

const enc = new TextEncoder()

/** SSE body; frames are split mid-event on purpose so clients must buffer. */
function sseResponse(events: ChatEvent[]): HttpResponse<ReadableStream> {
  const text = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')
  const cut = Math.floor(text.length / 3)
  const pieces = [text.slice(0, cut), text.slice(cut, cut * 2), text.slice(cut * 2)]
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const piece of pieces) controller.enqueue(enc.encode(piece))
      controller.close()
    },
  })
  return new HttpResponse(stream, { headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' } })
}

function libraryPlayable(song: Song): Playable {
  return {
    artist: song.artist,
    title: song.title,
    songId: song.id,
    coverUrl: song.coverArt ? `/api/cover/${song.coverArt}?size=300` : undefined,
    song,
  }
}

const notInLibrary: Playable = {
  artist: 'Mock Outsider',
  title: 'Somewhere Else',
  previewUrl: 'https://cdn.example.test/preview.mp3',
  youtubeUrl: 'https://www.youtube.com/watch?v=mock',
}

function mockTracks(): ChatTrack[] {
  return [
    ...songs.slice(0, 2).map((s) => ({ artist: s.artist, title: s.title, playable: libraryPlayable(s) })),
    { artist: notInLibrary.artist, title: notInLibrary.title, playable: notInLibrary },
  ]
}

function tokens(text: string): ChatEvent[] {
  return text.split(/(?<= )/).map((t) => ({ type: 'token', text: t }))
}

function reply(threadId: string, message: string, nowPlaying?: ChatRequest['nowPlaying']): ChatEvent[] {
  const answer = nowPlaying
    ? `Since you're playing **${nowPlaying.title}**, here are a few picks:`
    : `Here are a few picks for “${message}”:`
  return [
    { type: 'thread', threadId },
    ...tokens(answer),
    { type: 'tracks', tracks: mockTracks() },
    { type: 'suggestions', items: ['Want to save any of these to a playlist?', 'Should I dig deeper into any of these artists?'] },
    { type: 'done', message: answer },
  ]
}

let threads = 0

export function chatHandlers() {
  return [
    http.post('/api/chat', async ({ request }) => {
      const body = (await request.json()) as ChatRequest
      const threadId = body.threadId ?? `mock-thread-${++threads}`
      if (/\bsave\b/i.test(body.message)) {
        return sseResponse([
          { type: 'thread', threadId },
          { type: 'interrupt', kind: 'confirm_playlist_create', name: 'Mock Mix', trackCount: 3 },
        ])
      }
      return sseResponse(reply(threadId, body.message, body.nowPlaying))
    }),
    http.post('/api/chat/resume', async ({ request }) => {
      const { threadId, confirmed } = (await request.json()) as { threadId: string; confirmed: boolean }
      const message = confirmed
        ? "Saved playlist 'Mock Mix' to your library: 2 of 3 tracks matched."
        : 'Okay — I won’t save it.'
      return sseResponse([{ type: 'thread', threadId }, ...tokens(message), { type: 'done', message }])
    }),
    http.get('/api/playable', ({ request }) => {
      const q = new URL(request.url).searchParams
      const artist = q.get('artist') ?? ''
      const title = q.get('title') ?? ''
      const song = songs.find((s) => s.artist === artist && s.title.toLowerCase() === title.toLowerCase())
      return HttpResponse.json(song ? libraryPlayable(song) : { ...notInLibrary, artist, title })
    }),
  ]
}
