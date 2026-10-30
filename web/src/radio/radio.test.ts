import { describe, expect, it } from 'vitest'
import type { Playable, RadioQuery, RadioTrack, Song } from '@/api/types'
import { createPlayerStore } from '@/player/playerStore'
import { itemTitle, withUids } from '@/player/queue'
import { BACKOFF_MS, createRadio, queueExcludeKeys, radioKey, shouldRefill } from './radio'

const song = (title: string, artist = 'A'): Song => ({
  id: `id-${title}`,
  title,
  artist,
  artistId: 'ar',
  album: 'Al',
  albumId: 'al',
  duration: 100,
})

/** t<N> = library (playable inline), p<N> = preview via resolve, y<N> = nothing playable. */
function track(title: string, artist = 'B'): RadioTrack {
  if (title.startsWith('t'))
    return { artist, title, source: 'library', playable: { artist, title, songId: `id-${title}`, song: song(title, artist) } }
  return { artist, title, source: 'discover' }
}

function setup(answers: RadioTrack[][], opts: { enabled?: boolean } = {}) {
  const player = createPlayerStore({ rng: () => 0, onPlayIntent: () => {}, currentTime: () => 0 })
  const queries: RadioQuery[] = []
  const resolved: string[] = []
  let clock = 1_000
  const radio = createRadio({
    player,
    batch: 3,
    enabled: opts.enabled ?? true,
    persist: () => {},
    now: () => clock,
    fetchRadio: async (q) => {
      queries.push(q)
      return answers.shift() ?? []
    },
    resolve: async (t): Promise<Playable> => {
      resolved.push(t.title)
      return t.title.startsWith('p') ? { artist: t.artist, title: t.title, previewUrl: `/${t.title}.mp3` } : { artist: t.artist, title: t.title }
    },
  })
  const titles = () => player.getState().queue.map(itemTitle)
  return { player, radio, queries, resolved, titles, tick: (ms: number) => (clock += ms) }
}

const settle = () => new Promise((r) => setTimeout(r, 0))
const lib = (...titles: string[]) => titles.map((t) => ({ kind: 'library' as const, song: song(t) }))

describe('shouldRefill', () => {
  const state = (n: number, index: number, repeat: 'off' | 'all' = 'off') => ({
    queue: withUids(lib(...Array.from({ length: n }, (_, i) => `s${i}`))),
    index,
    repeat,
  })
  it('fires with ≤2 tracks left after the current one', () => {
    expect(shouldRefill(state(5, 1))).toBe(false) // 3 left
    expect(shouldRefill(state(5, 2))).toBe(true) // 2 left
    expect(shouldRefill(state(1, 0))).toBe(true)
  })
  it('never fires on an empty queue or with repeat-all', () => {
    expect(shouldRefill(state(0, -1))).toBe(false)
    expect(shouldRefill(state(2, 1, 'all'))).toBe(false)
  })
})

describe('queueExcludeKeys', () => {
  it('lists song ids + encoded artist::title, upcoming first, capped', () => {
    const queue = withUids([
      ...lib('old'),
      ...lib('now'),
      { kind: 'preview', url: '/x.mp3', artist: 'A, B', title: 'Q::R' },
    ])
    const keys = queueExcludeKeys({ queue, index: 1 })
    expect(keys.slice(0, 3)).toEqual(['id-now', radioKey('A', 'now'), radioKey('A, B', 'Q::R')])
    expect(radioKey('A, B', 'Q::R')).toBe('a%2C%20b::q%3A%3Ar')
    expect(keys).toContain('id-old')
    const many = withUids(lib(...Array.from({ length: 200 }, (_, i) => `s${i}`)))
    expect(queueExcludeKeys({ queue: many, index: 0 })).toHaveLength(120)
  })
})

describe('radio refill', () => {
  it('appends resolved tracks when the queue runs low, seeded from the current track', async () => {
    const { player, queries, resolved, titles } = setup([[track('t1'), track('y1'), track('p1'), track('t2'), track('t3')]])
    player.getState().playNow(lib('seed', 'next'))
    await settle()
    expect(queries).toHaveLength(1)
    expect(queries[0]?.songId).toBe('id-seed')
    expect(queries[0]?.exclude).toEqual(expect.arrayContaining(['id-seed', 'id-next', radioKey('A', 'next')]))
    // y1 isn't playable → skipped; library items need no lookup
    expect(titles()).toEqual(['seed', 'next', 't1', 'p1', 't2'])
    expect(resolved).toEqual(['y1', 'p1'])
    const added = player.getState().queue.slice(2)
    expect(added.every((q) => q.radio)).toBe(true)
    expect(added[1]?.kind).toBe('preview')
  })

  it('does nothing while off, or while plenty is queued', async () => {
    const off = setup([[track('t1')]], { enabled: false })
    off.player.getState().playNow(lib('seed'))
    await settle()
    expect(off.queries).toEqual([])

    const full = setup([[track('t1')]])
    full.player.getState().playNow(lib('a', 'b', 'c', 'd'))
    await settle()
    expect(full.queries).toEqual([])
    full.player.getState().next() // 2 left now
    await settle()
    expect(full.queries).toHaveLength(1)
  })

  it('does not re-add tracks already queued or offered this session', async () => {
    const { player, queries, titles } = setup([
      [track('t1'), track('t2')],
      [track('t1'), track('t2'), track('t3')],
    ])
    player.getState().playNow(lib('seed'))
    await settle()
    expect(titles()).toEqual(['seed', 't1', 't2'])
    player.getState().next() // → t1, 1 left
    await settle()
    expect(queries).toHaveLength(2)
    expect(queries[1]?.exclude).toEqual(expect.arrayContaining([radioKey('B', 't1'), radioKey('B', 't2')]))
    expect(titles()).toEqual(['seed', 't1', 't2', 't3'])
  })

  it('backs off after an empty answer, retries after the backoff', async () => {
    const { player, queries, tick } = setup([[], [track('t1')]])
    player.getState().playNow(lib('seed'))
    await settle()
    expect(queries).toHaveLength(1)
    player.getState().addToQueue(lib('x')) // queue change → would refill again
    await settle()
    expect(queries).toHaveLength(1)
    tick(BACKOFF_MS + 1)
    player.getState().addToQueue(lib('y'))
    await settle()
    expect(queries).toHaveLength(2)
  })

  it('turning it on refills straight away', async () => {
    const { player, radio, queries } = setup([[track('t1')]], { enabled: false })
    player.getState().playNow(lib('seed'))
    await settle()
    radio.setEnabled(true)
    await settle()
    expect(queries).toHaveLength(1)
    expect(radio.store.getState().enabled).toBe(true)
  })
})

describe('radio start', () => {
  it('replaces the queue with the seed song + radio tracks and turns autoplay on', async () => {
    const { player, radio, queries, titles } = setup([[track('t1'), track('t2'), track('t3')]], { enabled: false })
    player.getState().playNow(lib('old'))
    const ok = await radio.start({ song: song('seed'), artist: 'A', title: 'seed' })
    expect(ok).toBe(true)
    expect(queries[0]).toMatchObject({ songId: 'id-seed', exclude: ['id-seed', radioKey('A', 'seed')] })
    expect(titles()).toEqual(['seed', 't1', 't2', 't3'])
    expect(radio.store.getState().enabled).toBe(true)
  })

  it('artist seed: nothing playable → false, queue untouched', async () => {
    const { player, radio, queries, titles } = setup([[track('y1'), track('y2')]], { enabled: false })
    player.getState().playNow(lib('old'))
    expect(await radio.start({ artist: 'Nobody' })).toBe(false)
    expect(queries[0]).toMatchObject({ artist: 'Nobody' })
    expect(titles()).toEqual(['old'])
  })
})
