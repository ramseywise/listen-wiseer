import type { QueueItem, QueueState } from './queue'

// Extension points for P3. The audio engine and player store call these; today they
// are no-ops.
//   TODO(2): P3 — onTrackStarted → POST /api/player/scrobble (submission=false, "now playing")
//   TODO(2): P3 — onTrackProgress → scrobble submission=true once ≥50% or ≥240s played (once per play)
//   TODO(2): P3 — onTrackEnded → record ms_played / skipped (<30s) for DuckDB `plays`
//   TODO(2): P3 — onQueueChanged → debounced PUT /api/player/queue (savePlayQueue, D4)

export type TrackEndReason = 'ended' | 'skipped' | 'error'

export type TrackLifecycleHooks = {
  /** First `playing` event for a queue entry. */
  onTrackStarted: (item: QueueItem) => void
  /** Every `timeupdate` (~4 Hz) while playing. Positions in seconds. */
  onTrackProgress: (item: QueueItem, position: number, duration: number) => void
  /** The entry stopped being current (finished, skipped or failed). `listened` = seconds actually played. */
  onTrackEnded: (item: QueueItem, info: { reason: TrackEndReason; listened: number; duration: number }) => void
  /** Queue contents / order / index changed. */
  onQueueChanged: (state: QueueState) => void
}

const noop = () => {}

const defaults: TrackLifecycleHooks = {
  onTrackStarted: noop,
  onTrackProgress: noop,
  onTrackEnded: noop,
  onQueueChanged: noop,
}

export const lifecycle: TrackLifecycleHooks = { ...defaults }

/** Register hooks (P3 wires scrobbling + queue sync). Returns an unregister function. */
export function setLifecycleHooks(hooks: Partial<TrackLifecycleHooks>): () => void {
  Object.assign(lifecycle, hooks)
  return () => {
    for (const key of Object.keys(hooks) as (keyof TrackLifecycleHooks)[]) {
      ;(lifecycle as Record<keyof TrackLifecycleHooks, unknown>)[key] = defaults[key]
    }
  }
}
