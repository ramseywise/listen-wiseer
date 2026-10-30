import { create } from 'zustand'
import { api } from '@/api/client'
import type { Playable, RadioQuery, RadioTrack, Song } from '@/api/types'
import { playableToItem } from '@/archive/feeder'
import { isBoolean, readPref, writePref } from '@/lib/storage'
import { usePlayer } from '@/player/playerStore'
import type { PlayerStore } from '@/player/playerStore'
import { type QueueItem, type QueueItemInput, type QueueState, currentItem, itemArtist, itemTitle, upNext } from '@/player/queue'

// Radio / "Autoplay similar": when the queue is nearly done, ask /api/radio for tracks like
// the current one and append them. Library matches come back playable; the rest resolve
// lazily through /api/playable (preview → preview item, nothing playable → skipped), like the
// archive feeder. Appended items carry `radio: true` so the queue can mark them.

/** Refill once this many (or fewer) tracks are left after the current one. */
export const REFILL_AT = 2
/** Items appended per refill. */
export const BATCH = 5
/** Most exclude keys sent (keeps the GET URL short). */
export const EXCLUDE_CAP = 120
/** After an empty / failed refill, wait this long before asking again. */
export const BACKOFF_MS = 60_000

export type RadioSeed = { song?: Song; artist: string; title?: string }

export type RadioState = { enabled: boolean; loading: boolean }

type PlayerApi = { getState: () => PlayerStore; subscribe: (listener: () => void) => () => void }

export type RadioDeps = {
  fetchRadio: (q: RadioQuery) => Promise<RadioTrack[]>
  resolve: (t: RadioTrack) => Promise<Playable>
  player: PlayerApi
  now?: () => number
  batch?: number
  /** Initial "Autoplay similar" setting (default: the saved pref). */
  enabled?: boolean
  persist?: (enabled: boolean) => void
}

const enc = encodeURIComponent

/** `artist::title`, each side percent-encoded so commas/colons in names survive the join. */
export const radioKey = (artist: string, title: string) => `${enc(artist.toLowerCase())}::${enc(title.toLowerCase())}`

const itemKey = (item: QueueItemInput) => radioKey(itemArtist(item), itemTitle(item))

/** Exclude list for /api/radio: what's coming up first, then recent history; capped. */
export function queueExcludeKeys(state: Pick<QueueState, 'queue' | 'index'>, extra: Iterable<string> = []): string[] {
  const ahead = state.queue.slice(Math.max(0, state.index))
  const behind = state.queue.slice(0, Math.max(0, state.index)).reverse()
  const keys = new Set<string>()
  for (const item of [...ahead, ...behind]) {
    if (item.kind === 'library') keys.add(enc(item.song.id))
    keys.add(itemKey(item))
  }
  for (const k of extra) keys.add(k)
  return [...keys].slice(0, EXCLUDE_CAP)
}

/** Time to top up: something is playing, it's near the end, and the queue won't loop. */
export function shouldRefill(state: Pick<QueueState, 'queue' | 'index' | 'repeat'>): boolean {
  return state.index >= 0 && state.repeat !== 'all' && upNext(state).length <= REFILL_AT
}

function seedQuery(seed: RadioSeed): RadioQuery {
  return seed.song ? { songId: seed.song.id } : { artist: seed.artist, title: seed.title }
}

function seedOf(item: QueueItem): RadioSeed {
  return item.kind === 'library' ? { song: item.song, artist: item.song.artist, title: item.song.title } : { artist: item.artist, title: item.title }
}

export function createRadio(deps: RadioDeps) {
  const now = deps.now ?? Date.now
  const batch = deps.batch ?? BATCH
  const persist = deps.persist ?? ((on: boolean) => writePref('radio', on))
  const store = create<RadioState>(() => ({
    enabled: deps.enabled ?? readPref('radio', false, isBoolean),
    loading: false,
  }))
  /** Keys asked about this session (incl. unplayable ones) so they aren't offered again. */
  const tried = new Set<string>()
  let busy = false
  let backoffUntil = 0
  let generation = 0

  async function toItem(t: RadioTrack): Promise<QueueItemInput | null> {
    let playable = t.playable
    if (!playable) {
      try {
        playable = await deps.resolve(t)
      } catch {
        return null
      }
    }
    const item = playableToItem(playable)
    return item ? { ...item, radio: true } : null
  }

  /** Fetch + resolve up to `batch` playable items for `seed`. */
  async function fetchItems(seed: RadioSeed, exclude: string[]): Promise<QueueItemInput[]> {
    const tracks = await deps.fetchRadio({ ...seedQuery(seed), limit: batch * 3, exclude })
    const fresh = tracks.filter((t) => !tried.has(radioKey(t.artist, t.title)))
    const out: QueueItemInput[] = []
    for (let i = 0; i < fresh.length && out.length < batch; i += batch) {
      const chunk = fresh.slice(i, i + batch)
      for (const t of chunk) tried.add(radioKey(t.artist, t.title))
      const items = await Promise.all(chunk.map(toItem))
      out.push(...items.filter((x): x is QueueItemInput => x !== null))
    }
    return out.slice(0, batch)
  }

  async function refill(): Promise<void> {
    const st = deps.player.getState()
    const current = currentItem(st)
    if (!store.getState().enabled || busy || now() < backoffUntil || !current || !shouldRefill(st)) return
    busy = true
    const gen = generation
    store.setState({ loading: true })
    try {
      const items = await fetchItems(seedOf(current), queueExcludeKeys(st, tried))
      if (gen !== generation || !store.getState().enabled) return
      const queued = new Set(deps.player.getState().queue.map(itemKey))
      const add = items.filter((i) => !queued.has(itemKey(i)))
      if (add.length === 0) backoffUntil = now() + BACKOFF_MS
      else deps.player.getState().addToQueue(add)
    } catch {
      backoffUntil = now() + BACKOFF_MS
    } finally {
      busy = false
      store.setState({ loading: false })
    }
  }

  const unsubscribe = deps.player.subscribe(() => void refill())

  function setEnabled(enabled: boolean): void {
    store.setState({ enabled })
    persist(enabled)
    backoffUntil = 0
    if (enabled) void refill()
  }

  /**
   * Replace the queue with radio around `seed` (the seed song first, when it's in the
   * library) and turn autoplay on so it keeps going. False when nothing came back playable.
   */
  async function start(seed: RadioSeed): Promise<boolean> {
    generation++
    tried.clear()
    backoffUntil = 0
    store.setState({ loading: true })
    try {
      const first: QueueItemInput[] = seed.song ? [{ kind: 'library', song: seed.song }] : []
      const exclude = seed.song ? [enc(seed.song.id), radioKey(seed.artist, seed.title ?? '')] : []
      const items = await fetchItems(seed, exclude)
      if (first.length + items.length === 0) return false
      store.setState({ enabled: true })
      persist(true)
      deps.player.getState().playNow([...first, ...items])
      return true
    } finally {
      store.setState({ loading: false })
    }
  }

  return { store, start, setEnabled, refill, dispose: unsubscribe }
}

export type Radio = ReturnType<typeof createRadio>

export const radio = createRadio({
  fetchRadio: (q) => api.radio(q),
  resolve: (t) => api.playable(t),
  player: usePlayer,
})

export const useRadio = radio.store
