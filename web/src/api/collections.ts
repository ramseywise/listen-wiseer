import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { queryKeys } from './hooks'
import type { Playlist, PlaylistPatch, Song } from './types'

// P3 queries + mutations: Navidrome playlists, favourites (starred), archive.

export function usePlaylists() {
  return useQuery({ queryKey: queryKeys.playlists, queryFn: ({ signal }) => api.playlists(signal) })
}

export function usePlaylist(id: string) {
  return useQuery({
    queryKey: queryKeys.playlist(id),
    queryFn: ({ signal }) => api.playlist(id, signal),
    enabled: id !== '',
  })
}

export function useStarred() {
  return useQuery({ queryKey: queryKeys.starred, queryFn: ({ signal }) => api.starred(signal) })
}

/** Starred state for one song: the starred list wins once loaded, else the song's own flag. */
export function useIsStarred(song: Song | undefined): boolean {
  const { data } = useStarred()
  if (!song) return false
  return data ? data.some((s) => s.id === song.id) : song.starred === true
}

export function useArchivePlaylists() {
  return useQuery({
    queryKey: queryKeys.archive,
    queryFn: ({ signal }) => api.archivePlaylists(signal),
    staleTime: Infinity, // frozen archive
  })
}

export function useArchivePlaylist(id: string) {
  return useQuery({
    queryKey: queryKeys.archivePlaylist(id),
    queryFn: ({ signal }) => api.archivePlaylist(id, signal),
    enabled: id !== '',
    staleTime: Infinity,
  })
}

export function useCreatePlaylist() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, songIds = [] }: { name: string; songIds?: string[] }) => api.createPlaylist(name, songIds),
    onSuccess: (playlist) => {
      qc.setQueryData(queryKeys.playlist(playlist.id), playlist)
      void qc.invalidateQueries({ queryKey: queryKeys.playlists, exact: true })
    },
  })
}

/** PATCH a playlist. Rename, reorder (`songIds`) and removals are applied optimistically. */
export function useUpdatePlaylist() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: PlaylistPatch }) => api.updatePlaylist(id, patch),
    onMutate: async ({ id, patch }) => {
      const key = queryKeys.playlist(id)
      await qc.cancelQueries({ queryKey: key })
      const before = qc.getQueryData<Playlist>(key)
      if (before && (patch.songIds || patch.name || patch.removeIndexes?.length)) {
        const byId = new Map(before.songs.map((s) => [s.id, s]))
        const drop = new Set(patch.removeIndexes ?? [])
        const songs = patch.songIds
          ? patch.songIds.map((sid) => byId.get(sid)).filter((s): s is Song => s !== undefined)
          : before.songs.filter((_, i) => !drop.has(i))
        qc.setQueryData<Playlist>(key, { ...before, name: patch.name ?? before.name, songs, songCount: songs.length })
      }
      return { before }
    },
    onError: (_err, { id }, ctx) => {
      if (ctx?.before) qc.setQueryData(queryKeys.playlist(id), ctx.before)
    },
    onSuccess: (playlist) => {
      qc.setQueryData(queryKeys.playlist(playlist.id), playlist)
      void qc.invalidateQueries({ queryKey: queryKeys.playlists, exact: true })
    },
  })
}

export function useDeletePlaylist() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deletePlaylist(id),
    onSuccess: (_void, id) => {
      qc.removeQueries({ queryKey: queryKeys.playlist(id) })
      void qc.invalidateQueries({ queryKey: queryKeys.playlists, exact: true })
    },
  })
}

/** Like / unlike with an optimistic update of the starred list. */
export function useToggleStar() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ song, star }: { song: Song; star: boolean }) => (star ? api.star(song.id) : api.unstar(song.id)),
    onMutate: async ({ song, star }) => {
      await qc.cancelQueries({ queryKey: queryKeys.starred })
      const before = qc.getQueryData<Song[]>(queryKeys.starred)
      if (before) {
        const rest = before.filter((s) => s.id !== song.id)
        qc.setQueryData<Song[]>(queryKeys.starred, star ? [{ ...song, starred: true }, ...rest] : rest)
      }
      return { before }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.before) qc.setQueryData(queryKeys.starred, ctx.before)
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: queryKeys.starred }),
  })
}

export function useCopyArchive() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name?: string }) => api.copyArchive(id, name),
    onSuccess: ({ playlist }) => {
      qc.setQueryData(queryKeys.playlist(playlist.id), playlist)
      void qc.invalidateQueries({ queryKey: queryKeys.playlists, exact: true })
    },
  })
}
