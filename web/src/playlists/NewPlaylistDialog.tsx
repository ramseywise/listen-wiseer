import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { isLibraryOffline } from '@/api/client'
import { useCreatePlaylist } from '@/api/collections'
import { plural } from '@/lib/format'
import { NameDialog } from './NameDialog'
import { useNewPlaylistDialog } from './newPlaylist'

/** Mounted once; opened from the sidebar, the playlists page or a track menu. */
export function NewPlaylistDialog() {
  const { open, songIds } = useNewPlaylistDialog()
  const create = useCreatePlaylist()
  const navigate = useNavigate()
  const close = () => useNewPlaylistDialog.setState({ open: false, songIds: [] })
  return (
    <NameDialog
      open={open}
      onOpenChange={(o) => (o ? useNewPlaylistDialog.setState({ open: true }) : close())}
      title="New playlist"
      description={songIds.length ? `Starts with ${plural(songIds.length, 'song')}.` : 'Saved in your library, so other players see it too.'}
      submitLabel="Create"
      pending={create.isPending}
      onSubmit={(name) =>
        create.mutate(
          { name, songIds },
          {
            onSuccess: (playlist) => {
              close()
              toast.success(`Created "${playlist.name}"`)
              if (songIds.length === 0) void navigate(`/playlist/${encodeURIComponent(playlist.id)}`)
            },
            onError: (err) => toast.error(isLibraryOffline(err) ? 'Library is offline' : "Couldn't create the playlist"),
          },
        )
      }
    />
  )
}
