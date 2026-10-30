import { create } from 'zustand'
import { audioControls, usePlayback } from './audio'
import { lifecycle } from './lifecycle'
import {
  type QueueAction,
  type QueueItemInput,
  type QueueState,
  type Rng,
  initialQueueState,
  queueReducer,
  withUids,
} from './queue'

export type PlayerActions = {
  playNow: (items: QueueItemInput[], startIndex?: number) => void
  playNext: (items: QueueItemInput[]) => void
  addToQueue: (items: QueueItemInput[]) => void
  remove: (uid: string) => void
  move: (from: number, to: number) => void
  jumpTo: (index: number) => void
  next: () => void
  /** `currentTime` defaults to the audio element's position. */
  prev: (currentTime?: number) => void
  toggleShuffle: () => void
  cycleRepeat: () => void
  clear: () => void
}

export type PlayerStore = QueueState & PlayerActions

type Options = { rng?: Rng; currentTime?: () => number; onPlayIntent?: () => void }

/** Factory so tests can build an isolated store with a seeded RNG. */
export function createPlayerStore(opts: Options = {}) {
  const rng = opts.rng ?? Math.random
  const currentTime = opts.currentTime ?? (() => audioControls.currentTime())
  const onPlayIntent = opts.onPlayIntent ?? (() => usePlayback.setState({ intent: true }))

  return create<PlayerStore>()((set, get) => {
    const dispatch = (action: QueueAction) => {
      const prev = get()
      const next = queueReducer(prev, action, rng)
      if (next !== prev) set(next)
    }

    return {
      ...initialQueueState,
      playNow: (items, startIndex = 0) => {
        dispatch({ type: 'playNow', items: withUids(items), startIndex })
        onPlayIntent()
      },
      playNext: (items) => dispatch({ type: 'playNext', items: withUids(items) }),
      addToQueue: (items) => dispatch({ type: 'addToQueue', items: withUids(items) }),
      remove: (uid) => dispatch({ type: 'remove', uid }),
      move: (from, to) => dispatch({ type: 'move', from, to }),
      jumpTo: (index) => {
        dispatch({ type: 'jumpTo', index })
        onPlayIntent()
      },
      next: () => dispatch({ type: 'next' }),
      prev: (t) => dispatch({ type: 'prev', currentTime: t ?? currentTime() }),
      toggleShuffle: () => dispatch({ type: 'toggleShuffle' }),
      cycleRepeat: () => dispatch({ type: 'cycleRepeat' }),
      clear: () => dispatch({ type: 'clear' }),
    }
  })
}

export const usePlayer = createPlayerStore()

// P3 hook point: queue persistence (savePlayQueue).
usePlayer.subscribe((state, prev) => {
  if (state.queue !== prev.queue || state.index !== prev.index) lifecycle.onQueueChanged(state)
})
