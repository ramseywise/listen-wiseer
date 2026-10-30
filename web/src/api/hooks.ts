import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ApiError, api } from './client'
import type { AlbumListType } from './types'

export const queryKeys = {
  health: ['health'] as const,
  artists: ['artists'] as const,
  artist: (id: string) => ['artists', id] as const,
  albums: (type: AlbumListType, size: number, offset: number) => ['albums', type, size, offset] as const,
  album: (id: string) => ['album', id] as const,
  search: (q: string, limit: number) => ['search', q, limit] as const,
  playlists: ['playlists'] as const,
  playlist: (id: string) => ['playlists', id] as const,
  starred: ['starred'] as const,
  archive: ['archive'] as const,
  archivePlaylist: (id: string) => ['archive', id] as const,
  discover: ['discover'] as const,
}

/** Don't hammer a backend that told us Navidrome is down; don't retry 4xx. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && (error.status < 500 || error.status === 503)) return false
  return failureCount < 2
}

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => api.health(signal),
    refetchInterval: 60_000,
  })
}

export function useArtists() {
  return useQuery({ queryKey: queryKeys.artists, queryFn: ({ signal }) => api.artists(signal) })
}

export function useArtist(id: string) {
  return useQuery({
    queryKey: queryKeys.artist(id),
    queryFn: ({ signal }) => api.artist(id, signal),
    enabled: id !== '',
  })
}

export function useAlbumList(type: AlbumListType, size = 20, offset = 0) {
  return useQuery({
    queryKey: queryKeys.albums(type, size, offset),
    queryFn: ({ signal }) => api.albums({ type, size, offset }, signal),
    // random lists shouldn't reshuffle on every focus
    staleTime: type === 'random' ? Infinity : 60_000,
  })
}

export function useAlbum(id: string) {
  return useQuery({
    queryKey: queryKeys.album(id),
    queryFn: ({ signal }) => api.album(id, signal),
    enabled: id !== '',
  })
}

export function useSearch(q: string, limit = 20) {
  const trimmed = q.trim()
  return useQuery({
    queryKey: queryKeys.search(trimmed, limit),
    queryFn: ({ signal }) => api.search(trimmed, limit, signal),
    enabled: trimmed.length > 0,
    placeholderData: keepPreviousData,
  })
}

/** Discover page — the backend caches it for minutes; don't refetch on every focus. */
export function useDiscover() {
  return useQuery({
    queryKey: queryKeys.discover,
    queryFn: ({ signal }) => api.discover(false, signal),
    staleTime: 5 * 60_000,
    retry: shouldRetry,
  })
}
