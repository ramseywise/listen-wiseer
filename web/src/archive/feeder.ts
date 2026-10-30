import { create } from 'zustand'
import { api } from '@/api/client'
import type { ArchivePlaylist, ArchiveTrack, Playable } from '@/api/types'
import { usePlayer } from '@/player/playerStore'
import type { PlayerStore } from '@/player/playerStore'
import { type QueueItemInput, shuffled } from '@/player/queue'

// Plays an archive playlist by resolving tracks lazily through /api/playable: library song
// → else a 30s preview → else nothing playable (the row shows its YouTube link and the
// queue skips it). Only LOOKAHEAD tracks past the current one are resolved and queued; more
// are resolved as playback advances, so a 200-track playlist costs a few lookups up front.

export const LOOKAHEAD = 3

export type Resolution = { status: 'pending' } | { status: 'done'; playable: Playable } | { status: 'error' }

export type FeedState = { playlistId: string | null; resolutions: Record<string, Resolution> }

type PlayerApi = { getState: () => PlayerStore; subscribe: (listener: () => void) => () => void }

export type FeederDeps = {
  resolve: (track: ArchiveTrack) => Promise<Playable>
  player: PlayerApi
  lookahead?: number
  rng?: () => number
}

export const trackKey = (t: ArchiveTrack) => `${t.artist.toLowerCase()}\u0000${t.title.toLowerCase()}`

export function playableToItem(p: Playable): QueueItemInput | null {
  if (p.song) return { kind: 'library', song: p.song }
  if (p.previewUrl) return { kind: 'preview', url: p.previewUrl, artist: p.artist, title: p.title, coverUrl: p.coverUrl }
  return null
}

type Session = {
  playlistId: string
  tracks: ArchiveTrack[]
  order: number[]
  cursor: number
  own: Set<string>
  busy: boolean
  unsubscribe: () => void
}

export function createArchiveFeeder(deps: FeederDeps) {
  const lookahead = deps.lookahead ?? LOOKAHEAD
  const store = create<FeedState>(() => ({ playlistId: null, resolutions: {} }))
  const inflight = new Map<string, Promise<Playable | null>>()
  let session: Session | null = null

  const setResolution = (key: string, r: Resolution) =>
    store.setState((s) => ({ resolutions: { ...s.resolutions, [key]: r } }))

  function resolveTrack(track: ArchiveTrack): Promise<Playable | null> {
    const key = trackKey(track)
    const known = store.getState().resolutions[key]
    if (known?.status === 'done') return Promise.resolve(known.playable)
    const pending = inflight.get(key)
    if (pending) return pending
    setResolution(key, { status: 'pending' })
    const p = deps
      .resolve(track)
      .then((playable) => {
        setResolution(key, { status: 'done', playable })
        return playable
      })
      .catch(() => {
        setResolution(key, { status: 'error' })
        return null
      })
      .finally(() => inflight.delete(key))
    inflight.set(key, p)
    return p
  }

  const live = (s: Session) => session === s

  /** Resolve forward from the cursor until something playable turns up. */
  async function nextItem(s: Session): Promise<QueueItemInput | null> {
    while (s.cursor < s.order.length && live(s)) {
      const track = s.tracks[s.order[s.cursor++]!]!
      const playable = await resolveTrack(track)
      const item = playable ? playableToItem(playable) : null
      if (item) return item
    }
    return null
  }

  const lastUid = () => deps.player.getState().queue.at(-1)?.uid

  async function topUp(s: Session): Promise<void> {
    if (s.busy || !live(s)) return
    const st = deps.player.getState()
    if (!st.queue.some((q) => s.own.has(q.uid))) {
      stop() // the user replaced the queue
      return
    }
    let ahead = st.queue.slice(st.index + 1).filter((q) => s.own.has(q.uid)).length
    if (ahead >= lookahead || s.cursor >= s.order.length) return
    s.busy = true
    try {
      while (ahead < lookahead && live(s)) {
        const item = await nextItem(s)
        if (!item || !live(s)) break
        deps.player.getState().addToQueue([item])
        const uid = lastUid()
        if (uid) s.own.add(uid)
        ahead++
      }
    } finally {
      s.busy = false
    }
    if (live(s)) void topUp(s) // playback may have advanced while we were resolving
  }

  function stop(): void {
    session?.unsubscribe()
    session = null
  }

  /** Start playing `playlist` from `startIndex` (or shuffled). False when nothing is playable. */
  async function play(playlist: ArchivePlaylist, opts: { startIndex?: number; shuffle?: boolean } = {}): Promise<boolean> {
    stop()
    const indices = playlist.tracks.map((_, i) => i)
    const order = opts.shuffle ? shuffled(indices, deps.rng ?? Math.random) : indices.slice(opts.startIndex ?? 0)
    const s: Session = {
      playlistId: playlist.id,
      tracks: playlist.tracks,
      order,
      cursor: 0,
      own: new Set(),
      busy: false,
      unsubscribe: () => {},
    }
    session = s
    store.setState({ playlistId: playlist.id })
    const first = await nextItem(s)
    if (!live(s)) return false
    if (!first) {
      stop()
      return false
    }
    deps.player.getState().playNow([first])
    const uid = deps.player.getState().queue[0]?.uid // playNow of one item → it's the whole queue
    if (uid) s.own.add(uid)
    s.unsubscribe = deps.player.subscribe(() => void topUp(s))
    await topUp(s)
    return true
  }

  return {
    store,
    play,
    stop,
    resolveTrack,
    /** Tracks still to be resolved in the active session (tests / debugging). */
    remaining: () => (session ? session.order.length - session.cursor : 0),
  }
}

export type ArchiveFeeder = ReturnType<typeof createArchiveFeeder>

export const archiveFeeder = createArchiveFeeder({
  resolve: (track) => api.playable(track),
  player: usePlayer,
})

export function useResolution(track: ArchiveTrack): Resolution | undefined {
  return archiveFeeder.store((s) => s.resolutions[trackKey(track)])
}
