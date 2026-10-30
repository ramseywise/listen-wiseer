import { HttpResponse, http } from 'msw'
import type { AlbumListType } from '@/api/types'
import { chatHandlers } from './chat'
import { createCollectionHandlers } from './collections'
import { albums, artists, songs, toAlbumSummary, toArtistSummary } from './fixtures'
import { radioHandlers } from './radio'

/**
 * `full` = fixture library, `empty` = Navidrome up but nothing scanned (the real
 * state today), `offline` = Navidrome unreachable (503).
 * In the browser pick one with `?mock=empty` / `?mock=offline`.
 */
export type MockScenario = 'full' | 'empty' | 'offline'

function hashHue(id: string): number {
  let h = 0
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return h % 360
}

function coverSvg(id: string, size: number): string {
  const hue = hashHue(id)
  const hue2 = (hue + 50) % 360
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 100 100">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="hsl(${hue} 55% 45%)"/><stop offset="1" stop-color="hsl(${hue2} 60% 22%)"/>
</linearGradient></defs>
<rect width="100" height="100" fill="url(#g)"/>
<circle cx="50" cy="50" r="26" fill="none" stroke="rgba(255,255,255,.35)" stroke-width="1.5"/>
<circle cx="50" cy="50" r="6" fill="rgba(255,255,255,.55)"/>
</svg>`
}

function sortAlbums(type: AlbumListType) {
  const list = albums.map(toAlbumSummary)
  switch (type) {
    case 'newest':
      return list.sort((a, b) => (b.year ?? 0) - (a.year ?? 0))
    case 'alphabeticalByName':
      return list.sort((a, b) => a.name.localeCompare(b.name))
    case 'random':
      return list.sort(() => Math.random() - 0.5)
    case 'recent':
    case 'frequent':
      return list.reverse()
  }
}

const offline = () => HttpResponse.json({ detail: 'Navidrome is unreachable' }, { status: 503 })

export function createHandlers(scenario: MockScenario = 'full') {
  const empty = scenario === 'empty'
  const guard = scenario === 'offline' ? offline : null

  return [
    http.get('/api/health', () =>
      HttpResponse.json({ navidrome: scenario !== 'offline', songCount: empty || guard ? 0 : songs.length }),
    ),
    http.get('/api/artists', () => guard?.() ?? HttpResponse.json(empty ? [] : artists.map(toArtistSummary))),
    http.get('/api/artists/:id', ({ params }) => {
      if (guard) return guard()
      const a = empty ? undefined : artists.find((x) => x.id === params.id)
      return a ? HttpResponse.json(a) : HttpResponse.json({ detail: 'Artist not found' }, { status: 404 })
    }),
    http.get('/api/albums', ({ request }) => {
      if (guard) return guard()
      const url = new URL(request.url)
      const type = (url.searchParams.get('type') ?? 'recent') as AlbumListType
      const size = Number(url.searchParams.get('size') ?? 20)
      const offset = Number(url.searchParams.get('offset') ?? 0)
      return HttpResponse.json(empty ? [] : sortAlbums(type).slice(offset, offset + size))
    }),
    http.get('/api/albums/:id', ({ params }) => {
      if (guard) return guard()
      const a = empty ? undefined : albums.find((x) => x.id === params.id)
      return a ? HttpResponse.json(a) : HttpResponse.json({ detail: 'Album not found' }, { status: 404 })
    }),
    http.get('/api/search', ({ request }) => {
      if (guard) return guard()
      const url = new URL(request.url)
      const q = (url.searchParams.get('q') ?? '').toLowerCase()
      const limit = Number(url.searchParams.get('limit') ?? 20)
      const hit = (s: string) => q !== '' && !empty && s.toLowerCase().includes(q)
      return HttpResponse.json({
        artists: artists.filter((a) => hit(a.name)).map(toArtistSummary).slice(0, limit),
        albums: albums.filter((a) => hit(a.name) || hit(a.artist)).map(toAlbumSummary).slice(0, limit),
        songs: songs.filter((s) => hit(s.title) || hit(s.artist) || hit(s.album)).slice(0, limit),
      })
    }),
    http.get('/api/cover/:id', ({ params, request }) => {
      const size = Number(new URL(request.url).searchParams.get('size') ?? 300)
      return new HttpResponse(coverSvg(String(params.id), size), {
        headers: { 'Content-Type': 'image/svg+xml' },
      })
    }),
    // No audio bytes in mock mode — the player must surface this and skip.
    http.get('/api/stream/:id', () =>
      HttpResponse.json({ detail: 'Streaming is unavailable in mock mode' }, { status: 404 }),
    ),
    // P3: playlists, starred, scrobble, queue, archive, playable
    ...createCollectionHandlers(empty, guard),
    ...chatHandlers(),
    // P5: radio + Discover
    ...radioHandlers(empty, guard),
  ]
}
