import { Heart, ListPlus, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { isLibraryOffline } from '@/api/client'
import { useIsStarred, usePlaylists, useToggleStar, useUpdatePlaylist } from '@/api/collections'
import type { Song } from '@/api/types'
import {
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { openNewPlaylist } from '@/playlists/newPlaylist'

const failMessage = (err: unknown, what: string) => (isLibraryOffline(err) ? 'Library is offline' : `Couldn't ${what}`)

// Rendered inside an open DropdownMenuContent, so the queries only run once a menu opens.

export function AddToPlaylistSub({ song }: { song: Song }) {
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <ListPlus /> Add to playlist
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="max-h-80 w-56 overflow-y-auto">
        <PlaylistChoices song={song} />
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  )
}

function PlaylistChoices({ song }: { song: Song }) {
  const { data: playlists, isPending, isError } = usePlaylists()
  const update = useUpdatePlaylist()
  return (
    <>
      <DropdownMenuItem onSelect={() => openNewPlaylist([song.id])}>
        <Plus /> New playlist…
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      {isPending ? <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">Loading…</DropdownMenuLabel> : null}
      {isError ? (
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">Playlists unavailable</DropdownMenuLabel>
      ) : null}
      {playlists?.length === 0 ? (
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">No playlists yet</DropdownMenuLabel>
      ) : null}
      {playlists?.map((p) => (
        <DropdownMenuItem
          key={p.id}
          onSelect={() =>
            // mutateAsync: selecting closes the menu and unmounts this observer, which would drop mutate() callbacks
            update.mutateAsync({ id: p.id, patch: { add: [song.id] } }).then(
              () => toast.success(`Added to ${p.name}`, { description: song.title }),
              (err: unknown) => toast.error(failMessage(err, 'add to the playlist')),
            )
          }
        >
          <span className="truncate">{p.name}</span>
        </DropdownMenuItem>
      ))}
    </>
  )
}

export function LikeMenuItem({ song }: { song: Song }) {
  const starred = useIsStarred(song)
  const toggle = useToggleStar()
  return (
    <DropdownMenuItem
      onSelect={() =>
        toggle
          .mutateAsync({ song, star: !starred })
          .catch((err: unknown) => toast.error(failMessage(err, starred ? 'unlike' : 'like')))
      }
    >
      <Heart className={cn(starred && 'fill-primary text-primary')} /> {starred ? 'Unlike' : 'Like'}
    </DropdownMenuItem>
  )
}
