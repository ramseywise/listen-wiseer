import type { SavedQueue, SavedQueueState, Scrobble } from '@/api/types'
import type { TrackLifecycleHooks } from './lifecycle'
import { type QueueItem, type QueueState, currentItem, withUids } from './queue'

// Play tracking + queue persistence, plugged into the player through `setLifecycleHooks`.
//   start            → scrobble submission=false ("now playing")
//   ≥50% or ≥4 min   → scrobble submission=true, once per play
//   advanced < 30 s  → scrobble submission=true + skipped=true (recorded, not counted upstream)
//   queue change     → debounced PUT /api/player/queue (library items only)

/** Submit once this much has been listened to: half the track, capped at 4 minutes. */
export const SUBMIT_CAP_SECONDS = 240
/** Moving on before this many seconds counts as a skip. */
export const SKIP_THRESHOLD_SECONDS = 30
export const QUEUE_SAVE_DEBOUNCE_MS = 2000
/** While playing, re-save the queue at most this often so the resume position stays fresh. */
export const POSITION_SAVE_INTERVAL_MS = 15_000

export function submitThreshold(duration: number): number {
  return duration > 0 ? Math.min(duration / 2, SUBMIT_CAP_SECONDS) : SUBMIT_CAP_SECONDS
}

export type TrackerDeps = {
  scrobble: (body: Scrobble) => Promise<unknown>
  /** `keepalive` on the unload save, so the PUT survives the page going away. */
  saveQueue: (state: SavedQueueState, init?: { keepalive?: boolean }) => Promise<unknown>
  getQueue: () => QueueState
  /** Seconds into the current track. */
  currentTime: () => number
  now?: () => number
  debounceMs?: number
}

type Play = { uid: string; songId: string | undefined; listened: number; lastPos: number | null; submitted: boolean }

const songIdOf = (item: QueueItem | undefined) => (item?.kind === 'library' ? item.song.id : undefined)

/** Library-only snapshot of the queue for savePlayQueue. */
export function queueSnapshot(state: QueueState, position: number): SavedQueueState {
  const songIds = state.queue.flatMap((q) => (q.kind === 'library' ? [q.song.id] : []))
  const current = songIdOf(currentItem(state))
  return current ? { songIds, current, position: Math.max(0, position) } : { songIds, position: 0 }
}

export function createTracker(deps: TrackerDeps) {
  const now = deps.now ?? Date.now
  const debounceMs = deps.debounceMs ?? QUEUE_SAVE_DEBOUNCE_MS
  let play: Play | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  let lastSave = 0
  let suspended = false

  const send = (body: Scrobble) => void deps.scrobble(body).catch(() => {})

  const save = () => {
    timer = null
    lastSave = now()
    void deps.saveQueue(queueSnapshot(deps.getQueue(), deps.currentTime())).catch(() => {})
  }

  const scheduleSave = (delay = debounceMs) => {
    if (suspended) return
    if (timer) clearTimeout(timer)
    timer = setTimeout(save, delay)
  }

  const hooks: TrackLifecycleHooks = {
    onTrackStarted: (item) => {
      const songId = songIdOf(item)
      play = { uid: item.uid, songId, listened: 0, lastPos: null, submitted: false }
      if (songId) send({ songId, submission: false })
    },
    onTrackProgress: (item, position, duration) => {
      const p = play
      if (!p || p.uid !== item.uid) return
      if (p.lastPos !== null) {
        const delta = position - p.lastPos
        if (delta > 0 && delta < 1.5) p.listened += delta // seeks don't count as listening
      }
      p.lastPos = position
      if (p.songId && !p.submitted && p.listened >= submitThreshold(duration)) {
        p.submitted = true
        send({ songId: p.songId, submission: true, playedSeconds: Math.round(p.listened) })
      }
      if (!timer && now() - lastSave >= POSITION_SAVE_INTERVAL_MS) scheduleSave(0)
    },
    onTrackEnded: (item, { reason, listened }) => {
      const p = play
      play = null
      if (!p || p.uid !== item.uid || p.submitted || !p.songId) return
      if (reason === 'skipped' && listened < SKIP_THRESHOLD_SECONDS) {
        send({ songId: p.songId, submission: true, skipped: true, playedSeconds: Math.round(listened) })
      }
    },
    onQueueChanged: () => scheduleSave(),
  }

  return {
    hooks,
    /** Run `fn` without persisting the queue changes it makes (restore). */
    quietly(fn: () => void) {
      suspended = true
      try {
        fn()
      } finally {
        suspended = false
      }
    },
    /** Save now if a save is pending. */
    flush() {
      if (timer) {
        clearTimeout(timer)
        save()
      }
    },
    /**
     * Page is going away (pagehide / tab hidden): save now with `keepalive`, pending or not,
     * so the resume position is current. Skipped when there's nothing to save.
     */
    flushOnUnload() {
      if (timer) clearTimeout(timer)
      timer = null
      if (suspended) return
      const snapshot = queueSnapshot(deps.getQueue(), deps.currentTime())
      if (snapshot.songIds.length === 0) return
      lastSave = now()
      void deps.saveQueue(snapshot, { keepalive: true }).catch(() => {})
    },
    dispose() {
      if (timer) clearTimeout(timer)
      timer = null
      play = null
    },
  }
}

export type Tracker = ReturnType<typeof createTracker>

/** Queue state to load from a saved queue, or null when there's nothing to restore. */
export function restoredQueue(saved: SavedQueue, shuffle: boolean): Partial<QueueState> | null {
  if (saved.songs.length === 0) return null
  const queue = withUids(saved.songs.map((song) => ({ kind: 'library' as const, song })))
  const at = saved.current ? saved.songs.findIndex((s) => s.id === saved.current) : -1
  return { queue, index: Math.max(0, at), originalOrder: shuffle ? queue.map((q) => q.uid) : null }
}
