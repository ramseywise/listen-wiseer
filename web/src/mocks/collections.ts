import { HttpResponse, http } from 'msw'
import type {
  ArchivePlaylist,
  ArchiveTrack,
  Playable,
  Playlist,
  PlaylistPatch,
  PlaylistSummary,
  SavedQueueState,
  Scrobble,
  Song,
} from '@/api/types'
import { songs } from './fixtures'

// P3 mock routes: playlists, starred, scrobble, queue, archive, playable. State is per
// `createHandlers()` call, so `server.use(...createHandlers())` gives a test a fresh library.

type Guard = (() => Response) | null

const byId = new Map(songs.map((s) => [s.id, s]))
const song = (id: string) => byId.get(id) as Song

/** Archive tracks: some in the fixture library, some preview-only, one with only a YouTube link. */
const archiveFixtures: ArchivePlaylist[] = [
  {
    id: 'sp-1',
    name: 'Road Trip 2019',
    tracks: [
      { artist: 'Halcyon Drift', title: 'Harbour Lights' },
      { artist: 'Paper Lanterns', title: 'Ghost Song' },
      { artist: 'Nobody Known', title: 'Unfindable' },
      { artist: 'The Quiet Engines', title: 'Foundry Song' },
      { artist: 'Mira Okonkwo', title: 'Fig Tree' },
      { artist: 'Paper Lanterns', title: 'Deep Cut' },
      { artist: 'Velvet Cartography', title: 'Meridian' },
    ],
  },
  { id: 'sp-2', name: 'Untitled', tracks: [] },
]

const previews = new Set(['ghost song', 'deep cut'])

export function mockPlayable(t: { artist: string; title: string }): Playable {
  const hit = songs.find(
    (s) => s.artist.toLowerCase() === t.artist.toLowerCase() && s.title.toLowerCase() === t.title.toLowerCase(),
  )
  if (hit) return { artist: t.artist, title: t.title, songId: hit.id, song: hit, coverUrl: `/api/cover/${hit.coverArt}?size=300` }
  if (previews.has(t.title.toLowerCase()))
    return {
      artist: t.artist,
      title: t.title,
      previewUrl: `/mock-preview/${encodeURIComponent(t.title)}.mp3`,
      youtubeUrl: 'https://www.youtube.com/watch?v=mock',
    }
  return { artist: t.artist, title: t.title, youtubeUrl: 'https://www.youtube.com/watch?v=mock' }
}

function summary({ songs: _songs, ...rest }: Playlist): PlaylistSummary {
  return rest
}

const withCounts = (p: Omit<Playlist, 'songCount' | 'duration'>): Playlist => ({
  ...p,
  songCount: p.songs.length,
  duration: p.songs.reduce((t, s) => t + s.duration, 0),
})

const songsFor = (ids: string[]) => ids.map((id) => byId.get(id)).filter((s): s is Song => s !== undefined)

export function createCollectionHandlers(empty: boolean, guard: Guard) {
  let nextId = 2
  const playlists = new Map<string, Playlist>()
  const starred: string[] = []
  const scrobbles: Scrobble[] = []
  let queue: SavedQueueState = { songIds: [], position: 0 }
  if (!empty) {
    playlists.set('pl-1', withCounts({ id: 'pl-1', name: 'Evening Mix', coverArt: 'al-1', songs: songsFor(['al-1-t2', 'al-4-t1']) }))
    starred.push('al-5-t1')
  }

  const make = (name: string, ids: string[]): Playlist => {
    const list = songsFor(ids)
    const p = withCounts({ id: `pl-${nextId++}`, name, coverArt: list[0]?.coverArt, songs: list })
    playlists.set(p.id, p)
    return p
  }
  const notFound = () => HttpResponse.json({ detail: 'Playlist not found' }, { status: 404 })

  return [
    http.get('/api/playlists', () => guard?.() ?? HttpResponse.json([...playlists.values()].map(summary))),
    http.post('/api/playlists', async ({ request }) => {
      if (guard) return guard()
      const body = (await request.json()) as { name: string; songIds?: string[] }
      return HttpResponse.json(make(body.name, body.songIds ?? []), { status: 201 })
    }),
    http.get('/api/playlists/:id', ({ params }) => {
      if (guard) return guard()
      const p = playlists.get(String(params.id))
      return p ? HttpResponse.json(p) : notFound()
    }),
    http.patch('/api/playlists/:id', async ({ params, request }) => {
      if (guard) return guard()
      const p = playlists.get(String(params.id))
      if (!p) return notFound()
      const patch = (await request.json()) as PlaylistPatch
      const drop = new Set(patch.removeIndexes ?? [])
      const kept = (patch.songIds ? songsFor(patch.songIds) : p.songs).filter((_, i) => !drop.has(i))
      const updated = withCounts({ ...p, name: patch.name ?? p.name, songs: [...kept, ...songsFor(patch.add ?? [])] })
      playlists.set(p.id, updated)
      return HttpResponse.json(updated)
    }),
    http.delete('/api/playlists/:id', ({ params }) => {
      if (guard) return guard()
      return playlists.delete(String(params.id)) ? new HttpResponse(null, { status: 204 }) : notFound()
    }),
    http.get('/api/starred', () => guard?.() ?? HttpResponse.json(starred.map((id) => ({ ...song(id), starred: true })))),
    http.put('/api/starred/:id', ({ params }) => {
      if (guard) return guard()
      const id = String(params.id)
      if (!starred.includes(id)) starred.unshift(id)
      return new HttpResponse(null, { status: 204 })
    }),
    http.delete('/api/starred/:id', ({ params }) => {
      if (guard) return guard()
      const at = starred.indexOf(String(params.id))
      if (at >= 0) starred.splice(at, 1)
      return new HttpResponse(null, { status: 204 })
    }),
    http.post('/api/player/scrobble', async ({ request }) => {
      if (guard) return guard()
      scrobbles.push((await request.json()) as Scrobble)
      return new HttpResponse(null, { status: 204 })
    }),
    http.get('/api/player/queue', () =>
      guard?.() ??
      HttpResponse.json({ ...queue, songs: songsFor(queue.songIds) }),
    ),
    http.put('/api/player/queue', async ({ request }) => {
      if (guard) return guard()
      queue = (await request.json()) as SavedQueueState
      return new HttpResponse(null, { status: 204 })
    }),
    // archive lives in DuckDB, not Navidrome — available even when the library is offline
    http.get('/api/archive/playlists', () =>
      HttpResponse.json(empty ? [] : archiveFixtures.map((p) => ({ id: p.id, name: p.name, trackCount: p.tracks.length }))),
    ),
    http.get('/api/archive/playlists/:id', ({ params }) => {
      const p = empty ? undefined : archiveFixtures.find((x) => x.id === params.id)
      return p ? HttpResponse.json(p) : HttpResponse.json({ detail: 'Archive playlist not found' }, { status: 404 })
    }),
    http.post('/api/archive/playlists/:id/copy', async ({ params, request }) => {
      if (guard) return guard()
      const p = archiveFixtures.find((x) => x.id === params.id)
      if (!p) return HttpResponse.json({ detail: 'Archive playlist not found' }, { status: 404 })
      const body = (await request.json().catch(() => ({}))) as { name?: string }
      const unmatched: ArchiveTrack[] = []
      const ids: string[] = []
      for (const t of p.tracks) {
        const hit = mockPlayable(t).songId
        if (hit) ids.push(hit)
        else unmatched.push(t)
      }
      return HttpResponse.json({ playlist: make(body.name || p.name, ids), unmatched })
    }),
    http.get('/api/playable', ({ request }) => {
      const url = new URL(request.url)
      return HttpResponse.json(mockPlayable({ artist: url.searchParams.get('artist') ?? '', title: url.searchParams.get('title') ?? '' }))
    }),
  ]
}
