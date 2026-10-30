import type { Song } from '@/api/types'

// Pure queue reducer. No DOM, no audio, no time — everything the store does to the
// queue goes through `queueReducer`, which is what the Vitest suite covers.

export type QueueItemInput = (
  | { kind: 'library'; song: Song }
  | { kind: 'preview'; url: string; artist: string; title: string; coverUrl?: string }
) & {
  /** Appended by radio / "Autoplay similar" (marked in the queue UI). */
  radio?: boolean
}

/** A queue entry. `uid` is unique per entry so the same song can be queued twice. */
export type QueueItem = QueueItemInput & { uid: string }

export type RepeatMode = 'off' | 'all' | 'one'

export type QueueState = {
  queue: QueueItem[]
  /** Index of the current item in `queue`; -1 when the queue is empty. */
  index: number
  shuffle: boolean
  /** uids in un-shuffled order while shuffle is on, so toggling off restores it. */
  originalOrder: string[] | null
  repeat: RepeatMode
  /** Bumped when the current track should restart from 0 (prev >3s in, etc). */
  restartToken: number
}

export type QueueAction =
  | { type: 'playNow'; items: QueueItem[]; startIndex?: number }
  | { type: 'playNext'; items: QueueItem[] }
  | { type: 'addToQueue'; items: QueueItem[] }
  | { type: 'remove'; uid: string }
  | { type: 'move'; from: number; to: number }
  | { type: 'jumpTo'; index: number }
  | { type: 'next' }
  | { type: 'prev'; currentTime: number }
  | { type: 'toggleShuffle' }
  | { type: 'cycleRepeat' }
  | { type: 'clear' }

export type Rng = () => number

/** Seconds into a track after which "previous" restarts it instead of going back. */
export const PREV_RESTART_THRESHOLD = 3

export const initialQueueState: QueueState = {
  queue: [],
  index: -1,
  shuffle: false,
  originalOrder: null,
  repeat: 'off',
  restartToken: 0,
}

export function currentItem(state: QueueState): QueueItem | undefined {
  return state.index >= 0 ? state.queue[state.index] : undefined
}

/** Item that would play after the current one ends (honours repeat), for preloading. */
export function upcomingItem(state: QueueState): QueueItem | undefined {
  if (state.index < 0) return undefined
  if (state.repeat === 'one') return state.queue[state.index]
  if (state.index + 1 < state.queue.length) return state.queue[state.index + 1]
  return state.repeat === 'all' ? state.queue[0] : undefined
}

export function hasNext(state: QueueState): boolean {
  if (state.index < 0) return false
  return state.index + 1 < state.queue.length || state.repeat === 'all'
}

export function upNext(state: Pick<QueueState, 'queue' | 'index'>): QueueItem[] {
  return state.index < 0 ? [] : state.queue.slice(state.index + 1)
}

/** Fisher–Yates; returns a new array. */
export function shuffled<T>(items: readonly T[], rng: Rng): T[] {
  const out = items.slice()
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1))
    const tmp = out[i] as T
    out[i] = out[j] as T
    out[j] = tmp
  }
  return out
}

export function arrayMove<T>(items: readonly T[], from: number, to: number): T[] {
  const out = items.slice()
  const [moved] = out.splice(from, 1)
  if (moved !== undefined) out.splice(to, 0, moved)
  return out
}

function clampIndex(i: number, len: number): number {
  return Math.max(0, Math.min(i, len - 1))
}

function indexOfUid(queue: readonly QueueItem[], uid: string | undefined): number {
  return uid === undefined ? -1 : queue.findIndex((q) => q.uid === uid)
}

/** Put `first` at the front, shuffle everything else behind it. */
function shuffleAround(items: QueueItem[], first: QueueItem | undefined, rng: Rng): QueueItem[] {
  if (!first) return shuffled(items, rng)
  return [first, ...shuffled(items.filter((i) => i.uid !== first.uid), rng)]
}

export function queueReducer(state: QueueState, action: QueueAction, rng: Rng = Math.random): QueueState {
  switch (action.type) {
    case 'playNow': {
      const { items } = action
      if (items.length === 0) return { ...state, queue: [], index: -1, originalOrder: state.shuffle ? [] : null }
      const start = clampIndex(action.startIndex ?? 0, items.length)
      if (state.shuffle) {
        return {
          ...state,
          queue: shuffleAround(items, items[start], rng),
          index: 0,
          originalOrder: items.map((i) => i.uid),
        }
      }
      return { ...state, queue: items.slice(), index: start, originalOrder: null }
    }

    case 'playNext': {
      if (action.items.length === 0) return state
      const insertAt = state.index + 1
      const queue = [...state.queue.slice(0, insertAt), ...action.items, ...state.queue.slice(insertAt)]
      let originalOrder = state.originalOrder
      if (originalOrder) {
        const cur = currentItem(state)?.uid
        const at = cur === undefined ? originalOrder.length : originalOrder.indexOf(cur) + 1
        originalOrder = [...originalOrder.slice(0, at), ...action.items.map((i) => i.uid), ...originalOrder.slice(at)]
      }
      return { ...state, queue, index: state.index < 0 ? 0 : state.index, originalOrder }
    }

    case 'addToQueue': {
      if (action.items.length === 0) return state
      return {
        ...state,
        queue: [...state.queue, ...action.items],
        index: state.index < 0 ? 0 : state.index,
        originalOrder: state.originalOrder ? [...state.originalOrder, ...action.items.map((i) => i.uid)] : null,
      }
    }

    case 'remove': {
      const at = indexOfUid(state.queue, action.uid)
      if (at < 0) return state
      const queue = state.queue.filter((_, i) => i !== at)
      let index = state.index
      if (queue.length === 0) index = -1
      else if (at < state.index) index = state.index - 1
      // removing the current item: the next one slides into `index`; past the end → last
      else if (at === state.index) index = Math.min(state.index, queue.length - 1)
      return {
        ...state,
        queue,
        index,
        originalOrder: state.originalOrder ? state.originalOrder.filter((u) => u !== action.uid) : null,
      }
    }

    case 'move': {
      const { from, to } = action
      const len = state.queue.length
      if (from === to || from < 0 || to < 0 || from >= len || to >= len) return state
      const cur = currentItem(state)?.uid
      const queue = arrayMove(state.queue, from, to)
      return { ...state, queue, index: indexOfUid(queue, cur) }
    }

    case 'jumpTo': {
      if (action.index < 0 || action.index >= state.queue.length) return state
      if (action.index === state.index) return { ...state, restartToken: state.restartToken + 1 }
      return { ...state, index: action.index }
    }

    case 'next': {
      if (state.index < 0) return state
      if (state.index + 1 < state.queue.length) return { ...state, index: state.index + 1 }
      if (state.repeat === 'all') {
        // single-item queue wraps onto itself → restart instead
        return state.queue.length === 1
          ? { ...state, restartToken: state.restartToken + 1 }
          : { ...state, index: 0 }
      }
      return state
    }

    case 'prev': {
      if (state.index < 0) return state
      if (action.currentTime > PREV_RESTART_THRESHOLD) return { ...state, restartToken: state.restartToken + 1 }
      if (state.index > 0) return { ...state, index: state.index - 1 }
      if (state.repeat === 'all' && state.queue.length > 1) return { ...state, index: state.queue.length - 1 }
      return { ...state, restartToken: state.restartToken + 1 }
    }

    case 'toggleShuffle': {
      const cur = currentItem(state)
      if (!state.shuffle) {
        return {
          ...state,
          shuffle: true,
          originalOrder: state.queue.map((i) => i.uid),
          queue: shuffleAround(state.queue, cur, rng),
          index: cur ? 0 : -1,
        }
      }
      const byUid = new Map(state.queue.map((i) => [i.uid, i]))
      const restored: QueueItem[] = []
      for (const uid of state.originalOrder ?? []) {
        const item = byUid.get(uid)
        if (item) {
          restored.push(item)
          byUid.delete(uid)
        }
      }
      // anything not tracked in originalOrder (shouldn't happen) keeps its shuffled order at the end
      restored.push(...byUid.values())
      return {
        ...state,
        shuffle: false,
        originalOrder: null,
        queue: restored,
        index: cur ? indexOfUid(restored, cur.uid) : -1,
      }
    }

    case 'cycleRepeat': {
      const nextMode: Record<RepeatMode, RepeatMode> = { off: 'all', all: 'one', one: 'off' }
      return { ...state, repeat: nextMode[state.repeat] }
    }

    case 'clear':
      return { ...state, queue: [], index: -1, originalOrder: state.shuffle ? [] : null }
  }
}

let uidCounter = 0

export function makeUid(): string {
  uidCounter += 1
  const rand =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10)
  return `q${uidCounter}-${rand}`
}

export function withUids(items: readonly QueueItemInput[], uid: () => string = makeUid): QueueItem[] {
  return items.map((i) => ({ ...i, uid: uid() }))
}

export function itemTitle(item: QueueItemInput): string {
  return item.kind === 'library' ? item.song.title : item.title
}

export function itemArtist(item: QueueItemInput): string {
  return item.kind === 'library' ? item.song.artist : item.artist
}

export function itemKey(item: QueueItem): string {
  return item.kind === 'library' ? `lib:${item.song.id}` : `pre:${item.url}`
}
