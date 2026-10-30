import { describe, expect, it } from 'vitest'
import type { ArchivePlaylist, ArchiveTrack, Playable, Song } from '@/api/types'
import { createPlayerStore } from '@/player/playerStore'
import { itemTitle } from '@/player/queue'
import { createArchiveFeeder, playableToItem, trackKey } from './feeder'

const song = (title: string): Song => ({ id: `id-${title}`, title, artist: 'A', artistId: 'ar', album: 'Al', albumId: 'al', duration: 100 })

/** t<N> = in library, p<N> = preview only, y<N> = YouTube only. */
function fakeResolve(t: ArchiveTrack): Playable {
  if (t.title.startsWith('t')) return { artist: t.artist, title: t.title, songId: `id-${t.title}`, song: song(t.title) }
  if (t.title.startsWith('p')) return { artist: t.artist, title: t.title, previewUrl: `/${t.title}.mp3` }
  return { artist: t.artist, title: t.title, youtubeUrl: 'https://youtube.test/x' }
}

function playlist(...titles: string[]): ArchivePlaylist {
  return { id: 'sp', name: 'Old', tracks: titles.map((title) => ({ artist: 'A', title })) }
}

function setup(lookahead = 2) {
  const player = createPlayerStore({ rng: () => 0, onPlayIntent: () => {}, currentTime: () => 0 })
  const calls: string[] = []
  const feeder = createArchiveFeeder({
    player,
    lookahead,
    rng: () => 0,
    resolve: async (t) => {
      calls.push(t.title)
      return fakeResolve(t)
    },
  })
  const titles = () => player.getState().queue.map(itemTitle)
  return { player, feeder, calls, titles }
}

const settle = () => new Promise((r) => setTimeout(r, 0))

describe('playableToItem', () => {
  it('prefers the library song, then the preview, else nothing', () => {
    expect(playableToItem(fakeResolve({ artist: 'A', title: 't1' }))?.kind).toBe('library')
    expect(playableToItem(fakeResolve({ artist: 'A', title: 'p1' }))?.kind).toBe('preview')
    expect(playableToItem(fakeResolve({ artist: 'A', title: 'y1' }))).toBeNull()
  })
})

describe('archive feeder', () => {
  it('resolves only a few tracks ahead, not the whole playlist', async () => {
    const { feeder, calls, titles } = setup(2)
    const ok = await feeder.play(playlist('t1', 't2', 't3', 't4', 't5', 't6', 't7', 't8'))
    await settle()
    expect(ok).toBe(true)
    expect(titles()).toEqual(['t1', 't2', 't3'])
    expect(calls).toEqual(['t1', 't2', 't3'])
    expect(feeder.remaining()).toBe(5)
  })

  it('skips unplayable tracks and keeps their YouTube link for the row', async () => {
    const { feeder, titles } = setup(2)
    await feeder.play(playlist('y1', 'p1', 'y2', 't1', 't2'))
    await settle()
    expect(titles()).toEqual(['p1', 't1', 't2'])
    const r = feeder.store.getState().resolutions[trackKey({ artist: 'A', title: 'y1' })]
    expect(r).toEqual({ status: 'done', playable: expect.objectContaining({ youtubeUrl: 'https://youtube.test/x' }) })
  })

  it('tops up as playback advances', async () => {
    const { feeder, player, calls, titles } = setup(2)
    await feeder.play(playlist('t1', 't2', 't3', 't4', 't5'))
    await settle()
    player.getState().next()
    await settle()
    expect(titles()).toEqual(['t1', 't2', 't3', 't4'])
    expect(calls).toHaveLength(4)
  })

  it('starts from a row', async () => {
    const { feeder, titles } = setup(1)
    await feeder.play(playlist('t1', 't2', 't3', 't4'), { startIndex: 2 })
    await settle()
    expect(titles()).toEqual(['t3', 't4'])
  })

  it('stops feeding once the user replaces the queue', async () => {
    const { feeder, player, calls } = setup(1)
    await feeder.play(playlist('t1', 't2', 't3', 't4', 't5'))
    await settle()
    player.getState().playNow([{ kind: 'library', song: song('other') }])
    await settle()
    player.getState().addToQueue([{ kind: 'library', song: song('other2') }])
    player.getState().next()
    await settle()
    expect(calls).toEqual(['t1', 't2'])
  })

  it('reports nothing playable', async () => {
    const { feeder, player } = setup()
    expect(await feeder.play(playlist('y1', 'y2'))).toBe(false)
    expect(player.getState().queue).toEqual([])
  })

  it('shuffle permutes the resolve order', async () => {
    const { feeder, calls } = setup(0)
    await feeder.play(playlist('t1', 't2', 't3'), { shuffle: true })
    expect(calls).toHaveLength(1)
    expect(calls[0]).toBe('t2') // Fisher–Yates with rng=0 rotates [t1,t2,t3] → [t2,t3,t1]
  })

  it('reuses a resolution instead of asking twice', async () => {
    const { feeder, calls } = setup(0)
    await feeder.play(playlist('t1', 't2'))
    await feeder.play(playlist('t1', 't2'))
    expect(calls).toEqual(['t1'])
  })
})
