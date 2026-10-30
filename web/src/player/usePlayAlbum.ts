import { useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { toast } from 'sonner'
import { api, isLibraryOffline } from '@/api/client'
import { queryKeys } from '@/api/hooks'
import type { Song } from '@/api/types'
import { usePlayer } from './playerStore'
import type { QueueItemInput } from './queue'

export const songsToItems = (songs: Song[]): QueueItemInput[] => songs.map((song) => ({ kind: 'library', song }))

/** Fetch (or reuse cached) album tracks and play them, optionally shuffled. */
export function usePlayAlbum() {
  const qc = useQueryClient()
  return useCallback(
    async (albumId: string, opts: { shuffle?: boolean } = {}) => {
      try {
        const album = await qc.fetchQuery({
          queryKey: queryKeys.album(albumId),
          queryFn: ({ signal }) => api.album(albumId, signal),
        })
        playSongs(album.songs, 0, opts.shuffle)
      } catch (err) {
        toast.error(isLibraryOffline(err) ? 'Library is offline' : "Couldn't load that album")
      }
    },
    [qc],
  )
}

/** Play a list of songs; `shuffle` turns shuffle on and starts from a random track. */
export function playSongs(songs: Song[], startIndex = 0, shuffle?: boolean): void {
  if (songs.length === 0) return
  const player = usePlayer.getState()
  if (shuffle !== undefined && shuffle !== player.shuffle) player.toggleShuffle()
  const start = shuffle ? Math.floor(Math.random() * songs.length) : startIndex
  player.playNow(songsToItems(songs), start)
}
