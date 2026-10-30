import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SavedQueueState, Scrobble, Song } from '@/api/types'
import { type QueueItem, type QueueState, initialQueueState, withUids } from './queue'
import {
  QUEUE_SAVE_DEBOUNCE_MS,
  createTracker,
  queueSnapshot,
  restoredQueue,
  submitThreshold,
} from './tracking'

const song = (id: string, duration = 200): Song => ({
  id,
  title: id,
  artist: 'A',
  artistId: 'ar',
  album: 'Al',
  albumId: 'al',
  duration,
})

const libItem = (id: string, duration?: number): QueueItem => withUids([{ kind: 'library', song: song(id, duration) }])[0]!
const previewItem = (): QueueItem =>
  withUids([{ kind: 'preview', url: '/p.mp3', artist: 'P', title: 'Preview' }])[0]!

function setup(state: Partial<QueueState> = {}) {
  const scrobbles: Scrobble[] = []
  const saves: SavedQueueState[] = []
  const inits: ({ keepalive?: boolean } | undefined)[] = []
  let queue: QueueState = { ...initialQueueState, ...state }
  let time = 0
  const tracker = createTracker({
    scrobble: async (b) => void scrobbles.push(b),
    saveQueue: async (s, init) => {
      saves.push(s)
      inits.push(init)
    },
    getQueue: () => queue,
    currentTime: () => time,
    now: () => Date.now(),
  })
  return {
    tracker,
    hooks: tracker.hooks,
    scrobbles,
    saves,
    inits,
    setQueue: (q: Partial<QueueState>) => (queue = { ...queue, ...q }),
    setTime: (t: number) => (time = t),
  }
}

/** Simulate `seconds` of continuous playback as ~4 Hz timeupdates. */
function playFor(hooks: ReturnType<typeof setup>['hooks'], item: QueueItem, from: number, seconds: number, duration: number) {
  for (let t = from; t <= from + seconds + 1e-9; t += 0.25) hooks.onTrackProgress(item, t, duration)
}

describe('submitThreshold', () => {
  it('is half the track, capped at 4 minutes', () => {
    expect(submitThreshold(200)).toBe(100)
    expect(submitThreshold(600)).toBe(240)
    expect(submitThreshold(0)).toBe(240) // unknown duration
  })
})

describe('scrobbling', () => {
  it('sends now-playing on start', () => {
    const { hooks, scrobbles } = setup()
    hooks.onTrackStarted(libItem('s1'))
    expect(scrobbles).toEqual([{ songId: 's1', submission: false }])
  })

  it('submits once at 50% of a short track', () => {
    const { hooks, scrobbles } = setup()
    const item = libItem('s1', 100)
    hooks.onTrackStarted(item)
    playFor(hooks, item, 0, 49, 100)
    expect(scrobbles.filter((s) => s.submission)).toHaveLength(0)
    playFor(hooks, item, 49.25, 40, 100)
    const submitted = scrobbles.filter((s) => s.submission)
    expect(submitted).toHaveLength(1)
    expect(submitted[0]).toMatchObject({ songId: 's1', submission: true, playedSeconds: 50 })
    expect(submitted[0]!.skipped).toBeUndefined()
  })

  it('submits at 4 minutes of a long track', () => {
    const { hooks, scrobbles } = setup()
    const item = libItem('s1', 1200)
    hooks.onTrackStarted(item)
    playFor(hooks, item, 0, 239, 1200)
    expect(scrobbles.some((s) => s.submission)).toBe(false)
    playFor(hooks, item, 239.25, 2, 1200)
    expect(scrobbles.filter((s) => s.submission)).toHaveLength(1)
  })

  it('does not count a seek as listening', () => {
    const { hooks, scrobbles } = setup()
    const item = libItem('s1', 100)
    hooks.onTrackStarted(item)
    playFor(hooks, item, 0, 5, 100)
    playFor(hooks, item, 90, 5, 100) // jumped to the end
    expect(scrobbles.some((s) => s.submission)).toBe(false)
  })

  it('reports a skip before 30s as skipped', () => {
    const { hooks, scrobbles } = setup()
    const item = libItem('s1')
    hooks.onTrackStarted(item)
    hooks.onTrackEnded(item, { reason: 'skipped', listened: 12.4, duration: 200 })
    expect(scrobbles.at(-1)).toEqual({ songId: 's1', submission: true, skipped: true, playedSeconds: 12 })
  })

  it('a skip after 30s, a natural end or an error is not a skip', () => {
    for (const [reason, listened] of [
      ['skipped', 45],
      ['ended', 10],
      ['error', 1],
    ] as const) {
      const { hooks, scrobbles } = setup()
      const item = libItem('s1')
      hooks.onTrackStarted(item)
      hooks.onTrackEnded(item, { reason, listened, duration: 200 })
      expect(scrobbles.filter((s) => s.submission)).toEqual([])
    }
  })

  it('does not report a skip after the play was already submitted', () => {
    const { hooks, scrobbles } = setup()
    const item = libItem('s1', 40)
    hooks.onTrackStarted(item)
    playFor(hooks, item, 0, 21, 40)
    hooks.onTrackEnded(item, { reason: 'skipped', listened: 21, duration: 40 })
    expect(scrobbles.filter((s) => s.submission)).toHaveLength(1)
    expect(scrobbles.some((s) => s.skipped)).toBe(false)
  })

  it('ignores preview items', () => {
    const { hooks, scrobbles } = setup()
    const item = previewItem()
    hooks.onTrackStarted(item)
    playFor(hooks, item, 0, 30, 30)
    hooks.onTrackEnded(item, { reason: 'skipped', listened: 3, duration: 30 })
    expect(scrobbles).toEqual([])
  })

  it('counts each play of a repeated track separately', () => {
    const { hooks, scrobbles } = setup()
    const item = libItem('s1', 20)
    for (let i = 0; i < 2; i++) {
      hooks.onTrackStarted(item)
      playFor(hooks, item, 0, 20, 20)
      hooks.onTrackEnded(item, { reason: 'ended', listened: 20, duration: 20 })
    }
    expect(scrobbles.filter((s) => s.submission)).toHaveLength(2)
  })
})

describe('queue persistence', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('debounces queue changes into one save of library items only', () => {
    const items = [libItem('a'), previewItem(), libItem('b')]
    const t = setup({ queue: items, index: 2 })
    t.setTime(42.5)
    t.hooks.onQueueChanged(initialQueueState)
    vi.advanceTimersByTime(QUEUE_SAVE_DEBOUNCE_MS - 1)
    t.hooks.onQueueChanged(initialQueueState)
    vi.advanceTimersByTime(QUEUE_SAVE_DEBOUNCE_MS - 1)
    expect(t.saves).toEqual([])
    vi.advanceTimersByTime(1)
    expect(t.saves).toEqual([{ songIds: ['a', 'b'], current: 'b', position: 42.5 }])
  })

  it('does not save changes made quietly (restore)', () => {
    const t = setup({ queue: [libItem('a')], index: 0 })
    t.tracker.quietly(() => t.hooks.onQueueChanged(initialQueueState))
    vi.advanceTimersByTime(QUEUE_SAVE_DEBOUNCE_MS * 2)
    expect(t.saves).toEqual([])
  })

  it('flush saves a pending change immediately; dispose drops it', () => {
    const t = setup({ queue: [libItem('a')], index: 0 })
    t.hooks.onQueueChanged(initialQueueState)
    t.tracker.flush()
    expect(t.saves).toHaveLength(1)
    t.hooks.onQueueChanged(initialQueueState)
    t.tracker.dispose()
    vi.advanceTimersByTime(QUEUE_SAVE_DEBOUNCE_MS * 2)
    expect(t.saves).toHaveLength(1)
  })

  it('flushOnUnload saves now with keepalive, even with nothing pending', () => {
    const t = setup({ queue: [libItem('a'), libItem('b')], index: 1 })
    t.setTime(33)
    t.tracker.flushOnUnload()
    expect(t.saves).toEqual([{ songIds: ['a', 'b'], current: 'b', position: 33 }])
    expect(t.inits).toEqual([{ keepalive: true }])
    t.hooks.onQueueChanged(initialQueueState) // pending debounce is replaced, not doubled
    t.tracker.flushOnUnload()
    vi.advanceTimersByTime(QUEUE_SAVE_DEBOUNCE_MS * 2)
    expect(t.saves).toHaveLength(2)
  })

  it('flushOnUnload skips an empty / preview-only queue', () => {
    const t = setup({ queue: [previewItem()], index: 0 })
    t.tracker.flushOnUnload()
    expect(t.saves).toEqual([])
  })

  it('re-saves the position periodically while playing', () => {
    const item = libItem('a', 600)
    const t = setup({ queue: [item], index: 0 })
    t.hooks.onTrackStarted(item)
    vi.setSystemTime(100_000)
    t.hooks.onTrackProgress(item, 1, 600)
    vi.advanceTimersByTime(0)
    expect(t.saves).toHaveLength(1)
    vi.setSystemTime(105_000)
    t.hooks.onTrackProgress(item, 6, 600)
    vi.advanceTimersByTime(0)
    expect(t.saves).toHaveLength(1)
    vi.setSystemTime(116_000)
    t.hooks.onTrackProgress(item, 17, 600)
    vi.advanceTimersByTime(0)
    expect(t.saves).toHaveLength(2)
  })
})

describe('queueSnapshot / restoredQueue', () => {
  it('drops the position when the current item is a preview', () => {
    const state = { ...initialQueueState, queue: [libItem('a'), previewItem()], index: 1 }
    expect(queueSnapshot(state, 30)).toEqual({ songIds: ['a'], position: 0 })
  })

  it('restores at the saved current song, or the top', () => {
    const songs = [song('a'), song('b'), song('c')]
    const restored = restoredQueue({ songs, songIds: ['a', 'b', 'c'], current: 'b', position: 12 }, false)
    expect(restored?.index).toBe(1)
    expect(restored?.queue?.map((q) => (q.kind === 'library' ? q.song.id : ''))).toEqual(['a', 'b', 'c'])
    expect(restored?.originalOrder).toBeNull()
    expect(restoredQueue({ songs, songIds: ['a', 'b', 'c'], position: 0 }, true)?.index).toBe(0)
    expect(restoredQueue({ songs: [], songIds: [], position: 0 }, false)).toBeNull()
  })
})
