import {
  ListMusic,
  Loader2,
  Pause,
  Play,
  Radio,
  Repeat,
  Repeat1,
  Shuffle,
  SkipBack,
  SkipForward,
  Sparkles,
} from 'lucide-react'
import { Link } from 'react-router'
import { useToggleAssistant } from '@/hooks/useToggleAssistant'
import { CoverArt } from '@/components/music/CoverArt'
import { LikeButton } from '@/components/music/LikeButton'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useUi } from '@/lib/uiStore'
import { cn } from '@/lib/utils'
import { audioControls, usePlayback } from '@/player/audio'
import { itemCover } from '@/player/itemMeta'
import { usePlayer } from '@/player/playerStore'
import { type QueueItem, currentItem, itemArtist, itemTitle } from '@/player/queue'
import { radio, useRadio } from '@/radio/radio'
import { SeekBar } from './SeekBar'
import { VolumeControl } from './VolumeControl'

function IconButton({
  label,
  active,
  className,
  ...props
}: React.ComponentProps<typeof Button> & { label: string; active?: boolean }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={label}
          aria-pressed={active}
          className={cn(
            'size-9 text-muted-foreground hover:text-foreground',
            active && 'text-primary hover:text-primary',
            className,
          )}
          {...props}
        />
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  )
}

function NowPlaying({ item }: { item: QueueItem | undefined }) {
  if (!item) {
    return (
      <div className="flex min-w-0 items-center gap-3">
        <CoverArt src={undefined} alt="Nothing playing" className="size-12" />
        <div className="text-sm text-muted-foreground">Nothing playing</div>
      </div>
    )
  }
  return (
    <div className="flex min-w-0 items-center gap-3">
      <CoverArt src={itemCover(item, 120)} alt="" className="size-12 shadow" />
      <div className="min-w-0">
        <div className="truncate text-sm font-medium">
          {item.kind === 'library' ? (
            <Link to={`/album/${encodeURIComponent(item.song.albumId)}`} className="hover:underline">
              {itemTitle(item)}
            </Link>
          ) : (
            itemTitle(item)
          )}
        </div>
        <div className="truncate text-xs text-muted-foreground">
          {item.kind === 'library' ? (
            <Link to={`/artist/${encodeURIComponent(item.song.artistId)}`} className="hover:text-foreground hover:underline">
              {itemArtist(item)}
            </Link>
          ) : (
            <>
              {itemArtist(item)} <span className="ml-1 rounded bg-muted px-1 text-[10px] uppercase">preview</span>
            </>
          )}
        </div>
      </div>
      {item.kind === 'library' ? <LikeButton song={item.song} /> : null}
    </div>
  )
}

export function PlayerBar() {
  const item = usePlayer((s) => currentItem(s))
  const shuffle = usePlayer((s) => s.shuffle)
  const repeat = usePlayer((s) => s.repeat)
  const queueLength = usePlayer((s) => s.queue.length)
  const { next, prev, toggleShuffle, cycleRepeat } = usePlayer.getState()
  const isPlaying = usePlayback((s) => s.isPlaying)
  const isLoading = usePlayback((s) => s.isLoading)
  const queueOpen = useUi((s) => s.queueOpen)
  const setQueueOpen = useUi((s) => s.setQueueOpen)
  const assistant = useToggleAssistant()
  const radioOn = useRadio((s) => s.enabled)
  const radioLoading = useRadio((s) => s.loading)
  const hasItem = item !== undefined

  const repeatLabel = repeat === 'off' ? 'Repeat' : repeat === 'all' ? 'Repeat all' : 'Repeat one'

  return (
    <footer
      aria-label="Player"
      className="relative z-10 grid shrink-0 grid-cols-[1fr_auto] items-center gap-3 border-t bg-player px-3 py-2 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1fr)] md:px-4 md:py-3"
    >
      <NowPlaying item={item} />

      <div className="flex flex-col items-center gap-1">
        <div className="flex items-center gap-1">
          <IconButton label={shuffle ? 'Shuffle on' : 'Shuffle'} active={shuffle} onClick={toggleShuffle} className="max-md:hidden">
            <Shuffle />
          </IconButton>
          <IconButton label="Previous" onClick={() => prev()} disabled={!hasItem} className="max-md:hidden">
            <SkipBack className="fill-current" />
          </IconButton>
          <Button
            size="icon"
            onClick={audioControls.toggle}
            disabled={!hasItem}
            aria-label={isPlaying ? 'Pause' : 'Play'}
            className="size-10 rounded-full bg-foreground text-background hover:scale-105 hover:bg-foreground"
          >
            {isLoading && hasItem ? (
              <Loader2 className="animate-spin" />
            ) : isPlaying ? (
              <Pause className="fill-current" />
            ) : (
              <Play className="translate-x-px fill-current" />
            )}
          </Button>
          <IconButton label="Next" onClick={() => next()} disabled={!hasItem}>
            <SkipForward className="fill-current" />
          </IconButton>
          <IconButton label={repeatLabel} active={repeat !== 'off'} onClick={cycleRepeat} className="max-md:hidden">
            {repeat === 'one' ? <Repeat1 /> : <Repeat />}
          </IconButton>
          <IconButton label="Queue" active={queueOpen} onClick={() => setQueueOpen(!queueOpen)} className="md:hidden">
            <ListMusic />
          </IconButton>
          <IconButton label="Assistant" active={assistant.open} onClick={assistant.toggle} className="md:hidden">
            <Sparkles />
          </IconButton>
        </div>
        <SeekBar className="max-md:hidden" />
      </div>

      <div className="hidden items-center justify-end gap-1 md:flex">
        <IconButton
          label={radioOn ? 'Autoplay similar: on' : 'Autoplay similar'}
          active={radioOn}
          onClick={() => radio.setEnabled(!radioOn)}
        >
          {radioLoading ? <Loader2 className="animate-spin" /> : <Radio />}
        </IconButton>
        <IconButton label={`Queue (${queueLength})`} active={queueOpen} onClick={() => setQueueOpen(!queueOpen)}>
          <ListMusic />
        </IconButton>
        <IconButton label="Assistant" active={assistant.open} onClick={assistant.toggle}>
          <Sparkles />
        </IconButton>
        <VolumeControl />
      </div>

      {/* thin progress line on mobile */}
      <SeekBar compact className="absolute inset-x-0 -top-2 md:hidden" />
    </footer>
  )
}
