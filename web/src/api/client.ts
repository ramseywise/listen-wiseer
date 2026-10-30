import type {
  Album,
  AlbumListType,
  AlbumSummary,
  Artist,
  ArtistSummary,
  ArchiveCopyResult,
  ArchivePlaylist,
  ArchivePlaylistSummary,
  DiscoverPage,
  Health,
  Playable,
  Playlist,
  PlaylistPatch,
  PlaylistSummary,
  RadioQuery,
  RadioTrack,
  SavedQueue,
  SavedQueueState,
  Scrobble,
  SearchResults,
  Song,
} from './types'

const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }

  /** Backend returns 503 when Navidrome is unreachable. */
  get isLibraryOffline(): boolean {
    return this.status === 503
  }
}

export function isLibraryOffline(err: unknown): boolean {
  return err instanceof ApiError && err.isLibraryOffline
}

type Query = Record<string, string | number | undefined>

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== '') params.set(k, String(v))
  }
  const qs = params.toString()
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`
}

async function getJson<T>(path: string, query?: Query, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(new URL(buildUrl(path, query), window.location.href), { signal, headers: { Accept: 'application/json' } })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    // Network failure (backend down / proxy refused) — treat like library offline.
    throw new ApiError(503, 'API unreachable')
  }
  if (!res.ok) {
    let detail = res.statusText || 'Request failed'
    try {
      const body: unknown = await res.json()
      if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
        detail = body.detail
      }
    } catch {
      // non-JSON error body (e.g. proxy error page) — keep statusText
    }
    // Vite's proxy answers 502/504 when the API process isn't running.
    const status = res.status === 502 || res.status === 504 ? 503 : res.status
    throw new ApiError(status, detail)
  }
  return (await res.json()) as T
}

async function errorFrom(res: Response): Promise<ApiError> {
  let detail = res.statusText || 'Request failed'
  try {
    const body: unknown = await res.json()
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') detail = body.detail
  } catch {
    // non-JSON error body
  }
  return new ApiError(res.status === 502 || res.status === 504 ? 503 : res.status, detail)
}

/** POST/PUT/PATCH/DELETE with an optional JSON body; 204 → undefined. */
async function sendJson<T = void>(method: string, path: string, body?: unknown, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(new URL(buildUrl(path), window.location.href), {
      ...init,
      method,
      headers: { Accept: 'application/json', ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(503, 'API unreachable')
  }
  if (!res.ok) throw await errorFrom(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const enc = encodeURIComponent

export const api = {
  health: (signal?: AbortSignal) => getJson<Health>('/health', undefined, signal),
  artists: (signal?: AbortSignal) => getJson<ArtistSummary[]>('/artists', undefined, signal),
  artist: (id: string, signal?: AbortSignal) => getJson<Artist>(`/artists/${enc(id)}`, undefined, signal),
  albums: (
    params: { type: AlbumListType; size?: number; offset?: number },
    signal?: AbortSignal,
  ) => getJson<AlbumSummary[]>('/albums', params, signal),
  album: (id: string, signal?: AbortSignal) => getJson<Album>(`/albums/${enc(id)}`, undefined, signal),
  search: (q: string, limit = 20, signal?: AbortSignal) =>
    getJson<SearchResults>('/search', { q, limit }, signal),

  // P3 — playlists / favourites (Navidrome), play tracking, archive
  playlists: (signal?: AbortSignal) => getJson<PlaylistSummary[]>('/playlists', undefined, signal),
  playlist: (id: string, signal?: AbortSignal) => getJson<Playlist>(`/playlists/${enc(id)}`, undefined, signal),
  createPlaylist: (name: string, songIds: string[] = []) => sendJson<Playlist>('POST', '/playlists', { name, songIds }),
  updatePlaylist: (id: string, patch: PlaylistPatch) => sendJson<Playlist>('PATCH', `/playlists/${enc(id)}`, patch),
  deletePlaylist: (id: string) => sendJson('DELETE', `/playlists/${enc(id)}`),
  starred: (signal?: AbortSignal) => getJson<Song[]>('/starred', undefined, signal),
  star: (songId: string) => sendJson('PUT', `/starred/${enc(songId)}`),
  unstar: (songId: string) => sendJson('DELETE', `/starred/${enc(songId)}`),
  scrobble: (body: Scrobble) => sendJson('POST', '/player/scrobble', body),
  savedQueue: (signal?: AbortSignal) => getJson<SavedQueue>('/player/queue', undefined, signal),
  /** `keepalive` lets the PUT outlive the page (unload save; sendBeacon is POST-only). */
  saveQueue: (state: SavedQueueState, init?: { keepalive?: boolean }) => sendJson('PUT', '/player/queue', state, init),
  archivePlaylists: (signal?: AbortSignal) => getJson<ArchivePlaylistSummary[]>('/archive/playlists', undefined, signal),
  archivePlaylist: (id: string, signal?: AbortSignal) =>
    getJson<ArchivePlaylist>(`/archive/playlists/${enc(id)}`, undefined, signal),
  copyArchive: (id: string, name?: string) =>
    sendJson<ArchiveCopyResult>('POST', `/archive/playlists/${enc(id)}/copy`, name ? { name } : {}),
  playable: (track: { artist: string; title: string; mbid?: string }, signal?: AbortSignal) =>
    getJson<Playable>('/playable', { artist: track.artist, title: track.title, mbid: track.mbid }, signal),

  // P5 — radio + Discover
  radio: (q: RadioQuery, signal?: AbortSignal) =>
    getJson<RadioTrack[]>(
      '/radio',
      { songId: q.songId, artist: q.artist, title: q.title, limit: q.limit, exclude: q.exclude?.join(',') },
      signal,
    ),
  discover: (refresh = false, signal?: AbortSignal) =>
    getJson<DiscoverPage>('/discover', refresh ? { refresh: 'true' } : undefined, signal),
}

export function coverUrl(coverArtId: string | undefined, size = 300): string | undefined {
  if (!coverArtId) return undefined
  return buildUrl(`/cover/${enc(coverArtId)}`, { size })
}

export function streamUrl(songId: string): string {
  return buildUrl(`/stream/${enc(songId)}`)
}
