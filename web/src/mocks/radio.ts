import { HttpResponse, http } from 'msw'
import type { DiscoverPage, RadioTrack, Song } from '@/api/types'
import { mockPlayable } from './collections'
import { songs } from './fixtures'

// Mock /api/radio + /api/discover: library songs first, then "Ghost Song" (preview only) and
// an unplayable track, minus whatever `exclude` lists — like the real route.

const libraryTrack = (s: Song, reason: string): RadioTrack => ({
  artist: s.artist,
  title: s.title,
  source: 'library',
  reason,
  playable: mockPlayable(s),
})

const openWorld: RadioTrack[] = [
  { artist: 'Phantom Band', title: 'Ghost Song', source: 'discover', reason: 'Similar on Deezer' },
  { artist: 'Nobody Plays', title: 'Unplayable', source: 'corpus', reason: 'Sounds like it (your archive)' },
]

const keyOf = (artist: string, title: string) => `${artist.toLowerCase()}::${title.toLowerCase()}`

export function mockRadio(url: URL, empty: boolean): RadioTrack[] {
  if (empty) return []
  const seed = songs.find((s) => s.id === url.searchParams.get('songId'))
  const limit = Number(url.searchParams.get('limit') ?? 25)
  const excluded = new Set<string>()
  for (const raw of (url.searchParams.get('exclude') ?? '').split(',').filter(Boolean)) {
    const [artist, title] = raw.split('::')
    excluded.add(title === undefined ? raw : keyOf(decodeURIComponent(artist!), decodeURIComponent(title)))
  }
  const fresh = (t: RadioTrack) =>
    !excluded.has(keyOf(t.artist, t.title)) && !(t.playable?.songId && excluded.has(t.playable.songId))
  const library = songs
    .filter((s) => s.id !== seed?.id)
    .slice(0, 6)
    .map((s) => libraryTrack(s, 'Similar on Last.fm'))
  return [...library, ...openWorld].filter(fresh).slice(0, limit)
}

export function mockDiscover(empty: boolean): DiscoverPage {
  const free: RadioTrack = {
    artist: 'Open Source Orchestra',
    title: 'Creative Commons',
    source: 'discover',
    reason: 'Free on Internet Archive',
    free: {
      source: 'archive_org',
      downloadUrl: 'https://archive.org/download/oso/cc.mp3',
      pageUrl: 'https://archive.org/details/oso',
      licenseUrl: 'https://creativecommons.org/licenses/by/4.0/',
    },
  }
  return {
    sections: [
      {
        id: 'unplayed',
        title: 'In your library, not played yet',
        tracks: empty ? [] : songs.slice(-4).map((s) => libraryTrack(s, 'Never played')),
      },
      { id: 'new', title: 'New to you', tracks: empty ? [] : openWorld },
      { id: 'free', title: 'Free to download', tracks: empty ? [] : [free] },
    ],
  }
}

export function radioHandlers(empty: boolean, guard: (() => Response) | null) {
  return [
    http.get('/api/radio', ({ request }) => guard?.() ?? HttpResponse.json(mockRadio(new URL(request.url), empty))),
    http.get('/api/discover', () => guard?.() ?? HttpResponse.json(mockDiscover(empty))),
  ]
}
