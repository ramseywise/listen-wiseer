import { HttpResponse, http } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { createHandlers } from '@/mocks/handlers'
import { ApiError, api, coverUrl, isLibraryOffline, streamUrl } from './client'
import { shouldRetry } from './hooks'

const server = setupServer(...createHandlers('full'))
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('api client', () => {
  it('fetches typed lists', async () => {
    const artists = await api.artists()
    expect(artists.length).toBeGreaterThan(0)
    expect(artists[0]).toHaveProperty('albumCount')
    const albums = await api.albums({ type: 'newest', size: 2 })
    expect(albums).toHaveLength(2)
  })

  it('sends album list params', async () => {
    let seen: URL | undefined
    server.use(
      http.get('/api/albums', ({ request }) => {
        seen = new URL(request.url)
        return HttpResponse.json([])
      }),
    )
    await api.albums({ type: 'random', size: 5, offset: 10 })
    expect(seen?.searchParams.get('type')).toBe('random')
    expect(seen?.searchParams.get('size')).toBe('5')
    expect(seen?.searchParams.get('offset')).toBe('10')
  })

  it('encodes ids and search terms', async () => {
    let path = ''
    let q = ''
    server.use(
      http.get('/api/albums/:id', ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json({ id: 'x', name: 'n', artist: 'a', artistId: 'a', songCount: 0, duration: 0, songs: [] })
      }),
      http.get('/api/search', ({ request }) => {
        q = new URL(request.url).searchParams.get('q') ?? ''
        return HttpResponse.json({ artists: [], albums: [], songs: [] })
      }),
    )
    await api.album('a/b c')
    await api.search('rock & roll')
    expect(path).toBe('/api/albums/a%2Fb%20c')
    expect(q).toBe('rock & roll')
  })

  it('raises ApiError with the backend detail', async () => {
    await expect(api.album('missing')).rejects.toMatchObject({ status: 404, detail: 'Album not found' })
  })

  it('flags 503 as library offline', async () => {
    server.use(...createHandlers('offline'))
    const err = await api.artists().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(isLibraryOffline(err)).toBe(true)
  })

  it('maps proxy 502 to offline', async () => {
    server.use(http.get('/api/artists', () => new HttpResponse('Bad gateway', { status: 502 })))
    expect(isLibraryOffline(await api.artists().catch((e: unknown) => e))).toBe(true)
  })

  it('sends radio seed + exclude keys comma-joined', async () => {
    let seen: URL | undefined
    server.use(
      http.get('/api/radio', ({ request }) => {
        seen = new URL(request.url)
        return HttpResponse.json([])
      }),
    )
    await api.radio({ songId: 's1', limit: 10, exclude: ['s2', 'A%2C%20B::T'] })
    expect(seen?.searchParams.get('songId')).toBe('s1')
    expect(seen?.searchParams.get('limit')).toBe('10')
    expect(seen?.searchParams.get('exclude')).toBe('s2,A%2C%20B::T')
    expect(seen?.searchParams.has('artist')).toBe(false)
  })

  it('saves the queue with keepalive when asked (unload)', async () => {
    const spy = vi.spyOn(globalThis, 'fetch')
    try {
      await api.saveQueue({ songIds: ['s1'], current: 's1', position: 3 }, { keepalive: true })
      const init = spy.mock.calls[0]?.[1]
      expect(init?.method).toBe('PUT')
      expect(init?.keepalive).toBe(true)
      expect(JSON.parse(String(init?.body))).toEqual({ songIds: ['s1'], current: 's1', position: 3 })
    } finally {
      spy.mockRestore()
    }
  })

  it('builds cover and stream urls', () => {
    expect(coverUrl('al-1', 120)).toBe('/api/cover/al-1?size=120')
    expect(coverUrl(undefined)).toBeUndefined()
    expect(streamUrl('s 1')).toBe('/api/stream/s%201')
  })
})

describe('shouldRetry', () => {
  it('does not retry 4xx or 503', () => {
    expect(shouldRetry(0, new ApiError(404, 'x'))).toBe(false)
    expect(shouldRetry(0, new ApiError(503, 'x'))).toBe(false)
    expect(shouldRetry(0, new ApiError(500, 'x'))).toBe(true)
    expect(shouldRetry(2, new ApiError(500, 'x'))).toBe(false)
  })
})
