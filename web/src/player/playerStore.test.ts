import { describe, expect, it, vi } from 'vitest'
import type { Song } from '@/api/types'
import { setLifecycleHooks } from './lifecycle'
import { createPlayerStore, usePlayer } from './playerStore'
import { currentItem } from './queue'

const song = (id: string): Song => ({
  id,
  title: id,
  artist: 'A',
  artistId: 'ar',
  album: 'Al',
  albumId: 'al',
  duration: 60,
})
const lib = (...ids: string[]) => ids.map((id) => ({ kind: 'library' as const, song: song(id) }))

describe('createPlayerStore', () => {
  it('playNow assigns uids and signals play intent', () => {
    const onPlayIntent = vi.fn()
    const store = createPlayerStore({ onPlayIntent })
    store.getState().playNow(lib('a', 'a'), 1)
    const s = store.getState()
    expect(s.index).toBe(1)
    expect(s.queue[0]!.uid).not.toBe(s.queue[1]!.uid)
    expect(onPlayIntent).toHaveBeenCalledOnce()
  })

  it('prev reads the injected clock', () => {
    let t = 10
    const store = createPlayerStore({ currentTime: () => t, onPlayIntent: () => {} })
    store.getState().playNow(lib('a', 'b'), 1)
    store.getState().prev()
    expect(store.getState().index).toBe(1)
    expect(store.getState().restartToken).toBe(1)
    t = 1
    store.getState().prev()
    expect(store.getState().index).toBe(0)
  })

  it('an explicit prev time overrides the clock', () => {
    const store = createPlayerStore({ currentTime: () => 99, onPlayIntent: () => {} })
    store.getState().playNow(lib('a', 'b'), 1)
    store.getState().prev(0)
    expect(store.getState().index).toBe(0)
  })

  it('uses the injected rng for shuffle', () => {
    const make = () => {
      const store = createPlayerStore({ rng: () => 0.3, onPlayIntent: () => {} })
      store.getState().playNow(lib('a', 'b', 'c', 'd', 'e'))
      store.getState().toggleShuffle()
      return store.getState().queue.map((q) => (q.kind === 'library' ? q.song.id : ''))
    }
    expect(make()).toEqual(make())
  })

  it('does not notify subscribers for no-op actions', () => {
    const store = createPlayerStore({ onPlayIntent: () => {} })
    const listener = vi.fn()
    store.subscribe(listener)
    store.getState().next()
    store.getState().remove('missing')
    expect(listener).not.toHaveBeenCalled()
  })
})

describe('usePlayer singleton', () => {
  it('fires onQueueChanged for P3 queue persistence', () => {
    const onQueueChanged = vi.fn()
    const off = setLifecycleHooks({ onQueueChanged })
    usePlayer.getState().playNow(lib('x'))
    expect(onQueueChanged).toHaveBeenCalled()
    expect(currentItem(onQueueChanged.mock.calls.at(-1)![0])?.uid).toBe(usePlayer.getState().queue[0]!.uid)
    off()
    usePlayer.getState().clear()
  })
})
