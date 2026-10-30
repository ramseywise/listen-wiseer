// Mirrors "API contract (frozen for round 1)" in
// .claude/docs/plans/2026-10-30-player-app.md. camelCase, durations in seconds.

export type Song = {
  id: string
  title: string
  artist: string
  artistId: string
  album: string
  albumId: string
  track?: number
  year?: number
  duration: number
  coverArt?: string
  mbid?: string
  suffix?: string
  starred?: boolean
}

export type AlbumSummary = {
  id: string
  name: string
  artist: string
  artistId: string
  year?: number
  songCount: number
  duration: number
  coverArt?: string
}

export type Album = AlbumSummary & { songs: Song[] }

export type ArtistSummary = {
  id: string
  name: string
  albumCount: number
  coverArt?: string
}

export type Artist = ArtistSummary & { albums: AlbumSummary[] }

export type Health = { navidrome: boolean; songCount: number }

export type AlbumListType = 'recent' | 'newest' | 'frequent' | 'random' | 'alphabeticalByName'

export type SearchResults = {
  artists: ArtistSummary[]
  albums: AlbumSummary[]
  songs: Song[]
}

export type ApiErrorBody = { detail: string }

// ── P3: playlists, favourites, play tracking, archive ────────────────────────

export type PlaylistSummary = {
  id: string
  name: string
  songCount: number
  duration: number
  coverArt?: string
  changed?: string
}

export type Playlist = PlaylistSummary & { songs: Song[] }

/** PATCH /api/playlists/:id — `songIds` is a full rewrite (reorder); don't combine with add/removeIndexes. */
export type PlaylistPatch = { name?: string; songIds?: string[]; add?: string[]; removeIndexes?: number[] }

export type Scrobble = { songId: string; submission: boolean; playedSeconds?: number; skipped?: boolean }

/** `position` in seconds into `current`. */
export type SavedQueueState = { songIds: string[]; current?: string; position: number }

export type SavedQueue = SavedQueueState & { songs: Song[] }

export type ArchivePlaylistSummary = { id: string; name: string; trackCount: number }

export type ArchiveTrack = { artist: string; title: string; album?: string; mbid?: string }

export type ArchivePlaylist = { id: string; name: string; tracks: ArchiveTrack[] }

export type ArchiveCopyResult = { playlist: Playlist; unmatched: ArchiveTrack[] }

/** GET /api/playable — library song if matched, else a preview and/or a YouTube link. */
export type Playable = {
  artist: string
  title: string
  songId?: string
  previewUrl?: string
  youtubeUrl?: string
  coverUrl?: string
  song?: Song
}

// ── P4: assistant chat (/api/chat SSE) ───────────────────────────────────────

export type ChatTrack = { artist: string; title: string; mbid?: string; playable: Playable }

export type TrackBrief = { artist: string; title: string; album?: string }

export type ChatRequest = {
  threadId?: string
  message: string
  nowPlaying?: TrackBrief
  upNext?: TrackBrief[]
}

/** One SSE frame (`data: <json>\n\n`). `thread` always comes first; a turn ends at done / interrupt / error. */
export type ChatEvent =
  | { type: 'thread'; threadId: string }
  | { type: 'token'; text: string }
  | { type: 'tracks'; tracks: ChatTrack[] }
  | { type: 'suggestions'; items: string[] }
  | { type: 'interrupt'; kind: 'confirm_playlist_create'; name: string; trackCount: number }
  | { type: 'done'; message: string }
  | { type: 'error'; detail: string }

// ── P5: radio + Discover ─────────────────────────────────────────────────────

/** A legal free download (Jamendo CC / Internet Archive). No HTTP download route yet — link out. */
export type FreeDownload = { source: string; downloadUrl: string; pageUrl?: string; licenseUrl?: string }

/** `playable` only for library matches; resolve the rest lazily via /api/playable. */
export type RadioTrack = {
  artist: string
  title: string
  mbid?: string
  source: 'library' | 'corpus' | 'discover'
  reason?: string
  playable?: Playable
  free?: FreeDownload
}

export type RadioQuery = { songId?: string; artist?: string; title?: string; limit?: number; exclude?: string[] }

export type DiscoverSection = { id: string; title: string; tracks: RadioTrack[] }

export type DiscoverPage = { sections: DiscoverSection[] }
