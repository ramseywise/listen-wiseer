import { create } from 'zustand'

/** One app-wide "New playlist" dialog; `songIds` are added to the playlist it creates. */
export const useNewPlaylistDialog = create<{ open: boolean; songIds: string[] }>(() => ({ open: false, songIds: [] }))

export function openNewPlaylist(songIds: string[] = []): void {
  useNewPlaylistDialog.setState({ open: true, songIds })
}
