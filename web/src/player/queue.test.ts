import { describe, expect, it } from 'vitest'
import type { Song } from '@/api/types'
import {
  type QueueAction,
  type QueueItem,
  type QueueState,
  arrayMove,
  currentItem,
  hasNext,
  initialQueueState,
  itemKey,
  queueReducer,
  shuffled,
  upNext,
  upcomingItem,
  withUids,
} from './queue'

function song(id: string): Song {
  return { id, title: `Song ${id}`, artist: 'A', artistId: 'ar', album: 'Al', albumId: 'al', duration: 100 }
}

let n = 0
const uid = () => `u${++n}`

function items(...ids: string[]): QueueItem[] {
  return withUids(
    ids.map((id) => ({ kind: 'library' as const, song: song(id) })),
    uid,
  )
}

/** Deterministic RNG (mulberry32). */
function seeded(seed = 42) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const reduce = (state: QueueState, ...actions: QueueAction[]) =>
  actions.reduce((s, a) => queueReducer(s, a, seeded()), state)

const ids = (s: QueueState) => s.queue.map((q) => (q.kind === 'library' ? q.song.id : q.url))
const cur = (s: QueueState) => {
  const c = currentItem(s)
  return c?.kind === 'library' ? c.song.id : c?.url
}

const playing = (ids_: string[], start = 0) =>
  reduce(initialQueueState, { type: 'playNow', items: items(...ids_), startIndex: start })

describe('initial state', () => {
  it('is empty with no current item', () => {
    expect(initialQueueState.index).toBe(-1)
    expect(currentItem(initialQueueState)).toBeUndefined()
    expect(hasNext(initialQueueState)).toBe(false)
    expect(upNext(initialQueueState)).toEqual([])
    expect(upcomingItem(initialQueueState)).toBeUndefined()
  })
})

describe('playNow', () => {
  it('replaces the queue and starts at startIndex', () => {
    const s = playing(['a', 'b', 'c'], 1)
    expect(ids(s)).toEqual(['a', 'b', 'c'])
    expect(cur(s)).toBe('b')
  })

  it('defaults to index 0 and clamps an out-of-range start', () => {
    expect(playing(['a', 'b']).index).toBe(0)
    expect(playing(['a', 'b'], 9).index).toBe(1)
    expect(playing(['a', 'b'], -3).index).toBe(0)
  })

  it('replaces an existing queue entirely', () => {
    const s = reduce(playing(['a', 'b']), { type: 'playNow', items: items('x', 'y'), startIndex: 0 })
    expect(ids(s)).toEqual(['x', 'y'])
  })

  it('with an empty list clears the queue', () => {
    const s = reduce(playing(['a']), { type: 'playNow', items: [] })
    expect(s.queue).toEqual([])
    expect(s.index).toBe(-1)
  })

  it('with shuffle on puts the chosen track first and keeps the original order', () => {
    const shuffledState = reduce(initialQueueState, { type: 'toggleShuffle' })
    const list = items('a', 'b', 'c', 'd', 'e')
    const s = reduce(shuffledState, { type: 'playNow', items: list, startIndex: 2 })
    expect(cur(s)).toBe('c')
    expect(s.index).toBe(0)
    expect([...ids(s)].sort()).toEqual(['a', 'b', 'c', 'd', 'e'])
    expect(s.originalOrder).toEqual(list.map((i) => i.uid))
  })

  it('preserves repeat mode', () => {
    const s = reduce(initialQueueState, { type: 'cycleRepeat' }, { type: 'playNow', items: items('a') })
    expect(s.repeat).toBe('all')
  })
})

describe('playNext', () => {
  it('inserts right after the current item', () => {
    const s = reduce(playing(['a', 'b', 'c']), { type: 'playNext', items: items('x', 'y') })
    expect(ids(s)).toEqual(['a', 'x', 'y', 'b', 'c'])
    expect(cur(s)).toBe('a')
  })

  it('works mid-queue', () => {
    const s = reduce(playing(['a', 'b', 'c'], 1), { type: 'playNext', items: items('x') })
    expect(ids(s)).toEqual(['a', 'b', 'x', 'c'])
    expect(cur(s)).toBe('b')
  })

  it('on an empty queue makes the item current', () => {
    const s = reduce(initialQueueState, { type: 'playNext', items: items('x') })
    expect(ids(s)).toEqual(['x'])
    expect(s.index).toBe(0)
  })

  it('is a no-op for an empty list', () => {
    const s = playing(['a'])
    expect(queueReducer(s, { type: 'playNext', items: [] })).toBe(s)
  })

  it('while shuffled also inserts after current in the original order', () => {
    let s = reduce(playing(['a', 'b', 'c'], 1), { type: 'toggleShuffle' })
    s = reduce(s, { type: 'playNext', items: items('x') })
    expect(ids(s)[0]).toBe('b')
    expect(ids(s)[1]).toBe('x')
    s = reduce(s, { type: 'toggleShuffle' })
    expect(ids(s)).toEqual(['a', 'b', 'x', 'c'])
    expect(cur(s)).toBe('b')
  })
})

describe('addToQueue', () => {
  it('appends to the end without moving the current item', () => {
    const s = reduce(playing(['a', 'b']), { type: 'addToQueue', items: items('x') })
    expect(ids(s)).toEqual(['a', 'b', 'x'])
    expect(cur(s)).toBe('a')
  })

  it('on an empty queue sets index 0', () => {
    const s = reduce(initialQueueState, { type: 'addToQueue', items: items('x', 'y') })
    expect(s.index).toBe(0)
    expect(cur(s)).toBe('x')
  })

  it('is a no-op for an empty list', () => {
    const s = playing(['a'])
    expect(queueReducer(s, { type: 'addToQueue', items: [] })).toBe(s)
  })

  it('while shuffled appends to the original order too', () => {
    let s = reduce(playing(['a', 'b', 'c']), { type: 'toggleShuffle' })
    s = reduce(s, { type: 'addToQueue', items: items('z') })
    expect(ids(s).at(-1)).toBe('z')
    s = reduce(s, { type: 'toggleShuffle' })
    expect(ids(s)).toEqual(['a', 'b', 'c', 'z'])
  })

  it('allows the same song twice with distinct uids', () => {
    const s = reduce(playing(['a']), { type: 'addToQueue', items: items('a') })
    expect(ids(s)).toEqual(['a', 'a'])
    expect(s.queue[0]?.uid).not.toBe(s.queue[1]?.uid)
  })
})

describe('remove', () => {
  it('removes an item after the current one', () => {
    const s0 = playing(['a', 'b', 'c'])
    const s = reduce(s0, { type: 'remove', uid: s0.queue[2]!.uid })
    expect(ids(s)).toEqual(['a', 'b'])
    expect(cur(s)).toBe('a')
  })

  it('shifts the index when removing before the current item', () => {
    const s0 = playing(['a', 'b', 'c'], 2)
    const s = reduce(s0, { type: 'remove', uid: s0.queue[0]!.uid })
    expect(ids(s)).toEqual(['b', 'c'])
    expect(cur(s)).toBe('c')
  })

  it('removing the current item advances to the next one', () => {
    const s0 = playing(['a', 'b', 'c'], 1)
    const s = reduce(s0, { type: 'remove', uid: s0.queue[1]!.uid })
    expect(cur(s)).toBe('c')
  })

  it('removing the current last item falls back to the new last item', () => {
    const s0 = playing(['a', 'b', 'c'], 2)
    const s = reduce(s0, { type: 'remove', uid: s0.queue[2]!.uid })
    expect(cur(s)).toBe('b')
  })

  it('removing the only item empties the queue', () => {
    const s0 = playing(['a'])
    const s = reduce(s0, { type: 'remove', uid: s0.queue[0]!.uid })
    expect(s.queue).toEqual([])
    expect(s.index).toBe(-1)
  })

  it('removes only the targeted duplicate', () => {
    const s0 = reduce(playing(['a', 'b']), { type: 'addToQueue', items: items('a') })
    const s = reduce(s0, { type: 'remove', uid: s0.queue[2]!.uid })
    expect(ids(s)).toEqual(['a', 'b'])
    expect(s.queue[0]!.uid).toBe(s0.queue[0]!.uid)
  })

  it('ignores unknown uids', () => {
    const s = playing(['a'])
    expect(queueReducer(s, { type: 'remove', uid: 'nope' })).toBe(s)
  })

  it('while shuffled drops the uid from the original order', () => {
    let s = reduce(playing(['a', 'b', 'c']), { type: 'toggleShuffle' })
    const victim = s.queue.find((q) => q.kind === 'library' && q.song.id === 'b')!
    s = reduce(s, { type: 'remove', uid: victim.uid }, { type: 'toggleShuffle' })
    expect(ids(s)).toEqual(['a', 'c'])
  })
})

describe('move', () => {
  it('reorders up-next items and keeps the current item', () => {
    const s = reduce(playing(['a', 'b', 'c', 'd']), { type: 'move', from: 3, to: 1 })
    expect(ids(s)).toEqual(['a', 'd', 'b', 'c'])
    expect(cur(s)).toBe('a')
  })

  it('tracks the current item when it is moved', () => {
    const s = reduce(playing(['a', 'b', 'c'], 1), { type: 'move', from: 1, to: 2 })
    expect(ids(s)).toEqual(['a', 'c', 'b'])
    expect(s.index).toBe(2)
    expect(cur(s)).toBe('b')
  })

  it('tracks the current item when another moves across it', () => {
    const s = reduce(playing(['a', 'b', 'c'], 1), { type: 'move', from: 0, to: 2 })
    expect(ids(s)).toEqual(['b', 'c', 'a'])
    expect(cur(s)).toBe('b')
  })

  it('moves the right duplicate', () => {
    const s0 = reduce(playing(['a', 'x', 'a']), { type: 'move', from: 2, to: 1 })
    expect(ids(s0)).toEqual(['a', 'a', 'x'])
    expect(s0.index).toBe(0)
    expect(cur(s0)).toBe('a')
  })

  it('ignores out-of-range and no-op moves', () => {
    const s = playing(['a', 'b'])
    expect(queueReducer(s, { type: 'move', from: 0, to: 0 })).toBe(s)
    expect(queueReducer(s, { type: 'move', from: -1, to: 1 })).toBe(s)
    expect(queueReducer(s, { type: 'move', from: 0, to: 5 })).toBe(s)
  })
})

describe('jumpTo', () => {
  it('sets the current index', () => {
    expect(cur(reduce(playing(['a', 'b', 'c']), { type: 'jumpTo', index: 2 }))).toBe('c')
  })

  it('restarts when jumping to the current item', () => {
    const s0 = playing(['a', 'b'])
    const s = reduce(s0, { type: 'jumpTo', index: 0 })
    expect(s.restartToken).toBe(s0.restartToken + 1)
  })

  it('ignores invalid indices', () => {
    const s = playing(['a'])
    expect(queueReducer(s, { type: 'jumpTo', index: 4 })).toBe(s)
  })
})

describe('next', () => {
  it('advances', () => {
    expect(cur(reduce(playing(['a', 'b']), { type: 'next' }))).toBe('b')
  })

  it('stops at the end when repeat is off', () => {
    const s = playing(['a', 'b'], 1)
    expect(queueReducer(s, { type: 'next' })).toBe(s)
    expect(hasNext(s)).toBe(false)
  })

  it('wraps to the start with repeat all', () => {
    const s = reduce(playing(['a', 'b'], 1), { type: 'cycleRepeat' })
    expect(hasNext(s)).toBe(true)
    expect(cur(reduce(s, { type: 'next' }))).toBe('a')
  })

  it('restarts a single-item queue with repeat all', () => {
    const s0 = reduce(playing(['a']), { type: 'cycleRepeat' })
    const s = reduce(s0, { type: 'next' })
    expect(s.index).toBe(0)
    expect(s.restartToken).toBe(s0.restartToken + 1)
  })

  it('manual next still advances with repeat one', () => {
    const s = reduce(playing(['a', 'b']), { type: 'cycleRepeat' }, { type: 'cycleRepeat' })
    expect(s.repeat).toBe('one')
    expect(cur(reduce(s, { type: 'next' }))).toBe('b')
  })

  it('is a no-op on an empty queue', () => {
    expect(queueReducer(initialQueueState, { type: 'next' })).toBe(initialQueueState)
  })
})

describe('prev', () => {
  it('restarts the track when more than 3s in', () => {
    const s0 = playing(['a', 'b'], 1)
    const s = reduce(s0, { type: 'prev', currentTime: 3.5 })
    expect(cur(s)).toBe('b')
    expect(s.restartToken).toBe(s0.restartToken + 1)
  })

  it('goes back when 3s or less in', () => {
    expect(cur(reduce(playing(['a', 'b'], 1), { type: 'prev', currentTime: 3 }))).toBe('a')
    expect(cur(reduce(playing(['a', 'b'], 1), { type: 'prev', currentTime: 0.2 }))).toBe('a')
  })

  it('restarts at the first track when repeat is off', () => {
    const s0 = playing(['a', 'b'])
    const s = reduce(s0, { type: 'prev', currentTime: 0 })
    expect(cur(s)).toBe('a')
    expect(s.restartToken).toBe(s0.restartToken + 1)
  })

  it('wraps to the last track with repeat all', () => {
    const s = reduce(playing(['a', 'b', 'c']), { type: 'cycleRepeat' }, { type: 'prev', currentTime: 0 })
    expect(cur(s)).toBe('c')
  })

  it('is a no-op on an empty queue', () => {
    expect(queueReducer(initialQueueState, { type: 'prev', currentTime: 10 })).toBe(initialQueueState)
  })
})

describe('toggleShuffle', () => {
  const list = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']

  it('keeps the current item playing at the front and shuffles the rest', () => {
    const s = reduce(playing(list, 3), { type: 'toggleShuffle' })
    expect(s.shuffle).toBe(true)
    expect(s.index).toBe(0)
    expect(cur(s)).toBe('d')
    expect([...ids(s)].sort()).toEqual(list)
    expect(ids(s)).not.toEqual(['d', 'a', 'b', 'c', 'e', 'f', 'g', 'h'])
  })

  it('restores the original order and current item when turned off', () => {
    let s = reduce(playing(list, 3), { type: 'toggleShuffle' }, { type: 'next' }, { type: 'next' })
    const now = cur(s)
    s = reduce(s, { type: 'toggleShuffle' })
    expect(s.shuffle).toBe(false)
    expect(s.originalOrder).toBeNull()
    expect(ids(s)).toEqual(list)
    expect(cur(s)).toBe(now)
  })

  it('discards shuffled-order moves when restoring', () => {
    let s = reduce(playing(list), { type: 'toggleShuffle' }, { type: 'move', from: 5, to: 1 }, { type: 'toggleShuffle' })
    expect(ids(s)).toEqual(list)
    s = reduce(s, { type: 'toggleShuffle' })
    expect(s.shuffle).toBe(true)
  })

  it('works on an empty queue', () => {
    const on = reduce(initialQueueState, { type: 'toggleShuffle' })
    expect(on.shuffle).toBe(true)
    expect(on.index).toBe(-1)
    const off = reduce(on, { type: 'toggleShuffle' })
    expect(off.shuffle).toBe(false)
    expect(off.queue).toEqual([])
  })

  it('is deterministic for a given RNG', () => {
    const base = playing(list)
    const a = queueReducer(base, { type: 'toggleShuffle' }, seeded(7))
    const b = queueReducer(base, { type: 'toggleShuffle' }, seeded(7))
    expect(ids(a)).toEqual(ids(b))
  })
})

describe('cycleRepeat', () => {
  it('cycles off → all → one → off', () => {
    const modes = [1, 2, 3].map((k) =>
      reduce(initialQueueState, ...Array<QueueAction>(k).fill({ type: 'cycleRepeat' })).repeat,
    )
    expect(modes).toEqual(['all', 'one', 'off'])
  })
})

describe('clear', () => {
  it('empties the queue but keeps modes', () => {
    const s = reduce(playing(['a', 'b']), { type: 'cycleRepeat' }, { type: 'clear' })
    expect(s.queue).toEqual([])
    expect(s.index).toBe(-1)
    expect(s.repeat).toBe('all')
  })
})

describe('selectors', () => {
  it('upNext returns items after the current one', () => {
    expect(upNext(playing(['a', 'b', 'c'], 1)).map(itemKey)).toEqual(['lib:c'])
  })

  it('upcomingItem honours repeat modes', () => {
    const last = playing(['a', 'b'], 1)
    expect(upcomingItem(last)).toBeUndefined()
    const all = reduce(last, { type: 'cycleRepeat' })
    expect(itemKey(upcomingItem(all)!)).toBe('lib:a')
    const one = reduce(all, { type: 'cycleRepeat' })
    expect(itemKey(upcomingItem(one)!)).toBe('lib:b')
    expect(itemKey(upcomingItem(playing(['a', 'b']))!)).toBe('lib:b')
  })

  it('handles preview items', () => {
    const [p] = withUids([{ kind: 'preview', url: 'https://cdn/x.mp3', artist: 'X', title: 'Y' }], uid)
    const s = reduce(initialQueueState, { type: 'playNow', items: [p!] })
    expect(itemKey(currentItem(s)!)).toBe('pre:https://cdn/x.mp3')
  })
})

describe('helpers', () => {
  it('shuffled is a permutation and does not mutate input', () => {
    const input = [1, 2, 3, 4, 5]
    const out = shuffled(input, seeded(1))
    expect(input).toEqual([1, 2, 3, 4, 5])
    expect([...out].sort()).toEqual(input)
  })

  it('arrayMove moves forward and backward', () => {
    expect(arrayMove(['a', 'b', 'c', 'd'], 0, 2)).toEqual(['b', 'c', 'a', 'd'])
    expect(arrayMove(['a', 'b', 'c', 'd'], 3, 0)).toEqual(['d', 'a', 'b', 'c'])
  })

  it('withUids assigns unique ids', () => {
    const out = withUids([
      { kind: 'library', song: song('a') },
      { kind: 'library', song: song('a') },
    ])
    expect(new Set(out.map((o) => o.uid)).size).toBe(2)
  })
})
