import { Heart, ListEnd, ListPlus, ListStart, MoreHorizontal, Play, Radio } from 'lucide-react'
import type { ReactNode } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { usePlayer } from '@/player/playerStore'
import { type QueueItemInput, itemArtist, itemTitle } from '@/player/queue'
import { startRadio } from '@/radio/startRadio'
import { AddToPlaylistSub, LikeMenuItem } from './CollectionMenuItems'

type Props = {
  item: QueueItemInput
  label: string
  /** Play-now replaces the queue; the row passes its own context so play-now plays from here. */
  onPlayNow: () => void
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Context-specific items (e.g. "Remove from this playlist"), shown last. */
  extra?: ReactNode
}

export function TrackMenu({ item, label, onPlayNow, open, onOpenChange, extra }: Props) {
  const playNext = usePlayer((s) => s.playNext)
  const addToQueue = usePlayer((s) => s.addToQueue)

  return (
    <DropdownMenu open={open} onOpenChange={onOpenChange} modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`More options for ${label}`}
          className="size-8 text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
          onClick={(e) => e.stopPropagation()}
          onDoubleClick={(e) => e.stopPropagation()}
        >
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52" onClick={(e) => e.stopPropagation()}>
        <DropdownMenuLabel className="truncate text-xs font-normal text-muted-foreground">{label}</DropdownMenuLabel>
        <DropdownMenuItem onSelect={onPlayNow}>
          <Play /> Play now
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => {
            playNext([item])
            toast.success('Playing next', { description: label })
          }}
        >
          <ListStart /> Play next
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => {
            addToQueue([item])
            toast.success('Added to queue', { description: label })
          }}
        >
          <ListEnd /> Add to queue
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() =>
            void startRadio(
              item.kind === 'library'
                ? { song: item.song, artist: item.song.artist, title: item.song.title }
                : { artist: itemArtist(item), title: itemTitle(item) },
              label,
            )
          }
        >
          <Radio /> Start radio
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {item.kind === 'library' ? (
          <>
            <AddToPlaylistSub song={item.song} />
            <LikeMenuItem song={item.song} />
          </>
        ) : (
          <>
            <DropdownMenuItem disabled>
              <ListPlus /> Add to playlist
            </DropdownMenuItem>
            <DropdownMenuItem disabled>
              <Heart /> Like
            </DropdownMenuItem>
          </>
        )}
        {extra ? (
          <>
            <DropdownMenuSeparator />
            {extra}
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
