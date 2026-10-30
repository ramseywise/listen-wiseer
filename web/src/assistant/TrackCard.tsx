import { ExternalLink, ListPlus, MoreHorizontal, Play, Plus } from 'lucide-react'
import { toast } from 'sonner'
import type { ChatTrack } from '@/api/types'
import { AddToPlaylistSub } from '@/components/music/CollectionMenuItems'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { usePlayer } from '@/player/playerStore'
import type { QueueItemInput } from '@/player/queue'
import { queueItemFor } from './queueItem'

export function TrackCard({ track }: { track: ChatTrack }) {
  const playNow = usePlayer((s) => s.playNow)
  const addToQueue = usePlayer((s) => s.addToQueue)
  const { playable } = track
  const item = queueItemFor(track)
  const inLibrary = Boolean(playable.song)
  const label = `${track.title} by ${track.artist}`

  return (
    <li className="flex items-center gap-2.5 rounded-lg border bg-card/60 p-2" aria-label={label}>
      {playable.coverUrl ? (
        <img src={playable.coverUrl} alt="" className="size-10 shrink-0 rounded-md object-cover" loading="lazy" />
      ) : (
        <div className="size-10 shrink-0 rounded-md bg-muted" aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{track.title}</div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="truncate">{track.artist}</span>
          {!inLibrary ? (
            <span className="shrink-0 rounded bg-violet/15 px-1.5 py-px text-[10px] font-medium text-violet">
              {playable.previewUrl ? 'Preview · not in library' : 'Not in library'}
            </span>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center">
        {item ? (
          <>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Play ${label}${inLibrary ? '' : ' (preview)'}`}
              onClick={() => playNow([item])}
            >
              <Play />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Queue ${label}`}
              onClick={() => {
                addToQueue([item])
                toast.success('Added to queue', { description: label })
              }}
            >
              <Plus />
            </Button>
          </>
        ) : null}
        {playable.song ? (
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={`More options for ${label}`}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <AddToPlaylistSub song={playable.song} />
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
        {playable.youtubeUrl ? (
          <Button variant="ghost" size="icon-sm" asChild>
            <a href={playable.youtubeUrl} target="_blank" rel="noreferrer" aria-label={`${label} on YouTube`}>
              <ExternalLink />
            </a>
          </Button>
        ) : null}
      </div>
    </li>
  )
}

export function TrackCards({ tracks }: { tracks: ChatTrack[] }) {
  const addToQueue = usePlayer((s) => s.addToQueue)
  const items = tracks.map(queueItemFor).filter((i): i is QueueItemInput => i !== null)
  return (
    <div className="space-y-2">
      <ul className="space-y-1.5">
        {tracks.map((t) => (
          <TrackCard key={`${t.artist}\u0000${t.title}`} track={t} />
        ))}
      </ul>
      {items.length > 1 ? (
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => {
            addToQueue(items)
            toast.success(`Queued ${items.length} tracks`)
          }}
        >
          <ListPlus /> Queue all ({items.length})
        </Button>
      ) : null}
    </div>
  )
}
