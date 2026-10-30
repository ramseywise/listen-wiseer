import { AudioLines, Play } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { coverUrl } from '@/api/client'
import type { Song } from '@/api/types'
import { Skeleton } from '@/components/ui/skeleton'
import { formatTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePlayback } from '@/player/audio'
import { usePlayer } from '@/player/playerStore'
import { currentItem } from '@/player/queue'
import { playSongs } from '@/player/usePlayAlbum'
import { CoverArt } from './CoverArt'
import { TrackMenu } from './TrackMenu'

type Props = {
  songs: Song[]
  /** album view: show track numbers, hide album column & covers */
  variant?: 'album' | 'list'
  className?: string
}

export function TrackList({ songs, variant = 'list', className }: Props) {
  const currentSongId = usePlayer((s) => {
    const cur = currentItem(s)
    return cur?.kind === 'library' ? cur.song.id : undefined
  })
  return (
    <div role="list" className={cn('flex flex-col', className)}>
      {songs.map((song, i) => (
        <TrackRow
          key={`${song.id}-${i}`}
          song={song}
          position={i}
          variant={variant}
          active={song.id === currentSongId}
          onPlay={() => playSongs(songs, i)}
        />
      ))}
    </div>
  )
}

type RowProps = { song: Song; position: number; variant: 'album' | 'list'; active: boolean; onPlay: () => void }

function TrackRow({ song, position, variant, active, onPlay }: RowProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const isPlaying = usePlayback((s) => s.isPlaying)
  const label = `${song.title} — ${song.artist}`

  return (
    <div
      role="listitem"
      tabIndex={0}
      aria-current={active ? 'true' : undefined}
      onDoubleClick={onPlay}
      onClick={() => {
        // touch devices have no hover-revealed play button — a tap plays
        if (window.matchMedia?.('(hover: none)').matches) onPlay()
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onPlay()
      }}
      onContextMenu={(e) => {
        e.preventDefault()
        setMenuOpen(true)
      }}
      className={cn(
        'group grid h-14 grid-cols-[2rem_1fr_auto] items-center gap-3 rounded-md px-2 text-sm outline-none select-none hover:bg-accent/60 focus-visible:bg-accent/60 md:grid-cols-[2rem_1fr_minmax(0,14rem)_4rem_2rem]',
        variant === 'album' && 'md:grid-cols-[2rem_1fr_4rem_2rem]',
        active && 'text-primary',
      )}
    >
      <div className="relative flex size-8 items-center justify-center text-muted-foreground tabular-nums">
        <span className={cn('group-hover:invisible', active && 'invisible')}>
          {variant === 'album' ? (song.track ?? position + 1) : position + 1}
        </span>
        {active ? (
          <AudioLines className={cn('absolute size-4 text-primary group-hover:invisible', isPlaying && 'animate-pulse')} />
        ) : null}
        <button
          type="button"
          aria-label={`Play ${song.title}`}
          onClick={onPlay}
          className="invisible absolute inset-0 flex items-center justify-center text-foreground group-hover:visible"
        >
          <Play className="size-4 fill-current" />
        </button>
      </div>

      <div className="flex min-w-0 items-center gap-3">
        {variant === 'list' ? (
          <CoverArt src={coverUrl(song.coverArt, 80)} alt="" className="size-10 rounded" />
        ) : null}
        <div className="min-w-0">
          <div className={cn('truncate font-medium', active ? 'text-primary' : 'text-foreground')}>{song.title}</div>
          <Link
            to={`/artist/${encodeURIComponent(song.artistId)}`}
            onClick={(e) => e.stopPropagation()}
            className="block truncate text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            {song.artist}
          </Link>
        </div>
      </div>

      {variant === 'list' ? (
        <Link
          to={`/album/${encodeURIComponent(song.albumId)}`}
          onClick={(e) => e.stopPropagation()}
          className="hidden truncate text-xs text-muted-foreground hover:text-foreground hover:underline md:block"
        >
          {song.album}
        </Link>
      ) : null}

      <div className="hidden text-right text-xs text-muted-foreground tabular-nums md:block">{formatTime(song.duration)}</div>

      <TrackMenu
        item={{ kind: 'library', song }}
        label={label}
        onPlayNow={onPlay}
        open={menuOpen}
        onOpenChange={setMenuOpen}
      />
    </div>
  )
}

export function TrackListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-1" aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex h-14 items-center gap-3 px-2">
          <Skeleton className="size-6" />
          <Skeleton className="size-10" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-1/3" />
            <Skeleton className="h-3 w-1/5" />
          </div>
          <Skeleton className="h-3 w-10" />
        </div>
      ))}
    </div>
  )
}
