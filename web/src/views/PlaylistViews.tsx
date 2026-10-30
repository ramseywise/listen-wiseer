import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Clock, GripVertical, Heart, ListMusic, Pencil, Play, Plus, Shuffle, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { coverUrl, isLibraryOffline } from '@/api/client'
import { useDeletePlaylist, usePlaylist, usePlaylists, useStarred, useUpdatePlaylist } from '@/api/collections'
import type { Playlist, Song } from '@/api/types'
import { CardGrid, CardSkeletons } from '@/components/music/CardGrid'
import { CoverArt } from '@/components/music/CoverArt'
import { PageHeader, PageHeaderSkeleton } from '@/components/music/PageHeader'
import { TrackList, TrackListSkeleton } from '@/components/music/TrackList'
import { TrackMenu } from '@/components/music/TrackMenu'
import { EmptyState, ErrorState } from '@/components/states/States'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { formatTime, formatTotal, plural } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePlayer } from '@/player/playerStore'
import { arrayMove, currentItem } from '@/player/queue'
import { playSongs } from '@/player/usePlayAlbum'
import { NameDialog } from '@/playlists/NameDialog'
import { openNewPlaylist } from '@/playlists/newPlaylist'

const failMessage = (err: unknown, what: string) => (isLibraryOffline(err) ? 'Library is offline' : `Couldn't ${what}`)

export function PlaylistsView() {
  const { data, isPending, isError, error, refetch } = usePlaylists()
  const newButton = (
    <Button variant="outline" size="sm" onClick={() => openNewPlaylist()}>
      <Plus /> New playlist
    </Button>
  )
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight">Playlists</h1>
        {newButton}
      </div>
      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <CardGrid>
          <Link
            to="/liked"
            className="group block w-full rounded-lg p-2 transition-colors outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring"
          >
            <div className="flex aspect-square w-full items-center justify-center rounded-md bg-gradient-to-br from-primary/60 to-violet/60 text-white shadow-md">
              <Heart className="size-1/4 fill-current" />
            </div>
            <div className="mt-2 truncate text-sm font-medium">Liked Songs</div>
          </Link>
          {isPending ? <CardSkeletons count={4} /> : null}
          {data?.map((p) => (
            <Link
              key={p.id}
              to={`/playlist/${encodeURIComponent(p.id)}`}
              className="group block w-full rounded-lg p-2 transition-colors outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring"
            >
              <CoverArt src={coverUrl(p.coverArt, 300)} alt={`${p.name} cover`} className="w-full shadow-md shadow-black/20" />
              <div className="mt-2 truncate text-sm font-medium">{p.name}</div>
              <div className="truncate text-xs text-muted-foreground">{plural(p.songCount, 'song')}</div>
            </Link>
          ))}
        </CardGrid>
      )}
      {data?.length === 0 ? (
        <EmptyState icon={<ListMusic />} title="No playlists yet" action={newButton}>
          Playlists live in your Navidrome library, so phone apps see them too. Add tracks from any track menu.
        </EmptyState>
      ) : null}
    </div>
  )
}

type Row = { key: string; song: Song; index: number }

function SortableTrack({
  row,
  active,
  onPlay,
  onRemove,
}: {
  row: Row
  active: boolean
  onPlay: () => void
  onRemove: () => void
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: row.key })
  const { song } = row
  const label = `${song.title} — ${song.artist}`
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-testid="playlist-row"
      onDoubleClick={onPlay}
      className={cn(
        'group grid h-14 grid-cols-[1.5rem_1fr_auto_2rem] items-center gap-3 rounded-md px-1 text-sm hover:bg-accent/60 md:grid-cols-[1.5rem_1fr_minmax(0,14rem)_4rem_2rem]',
        isDragging && 'relative z-10 bg-accent shadow-lg',
      )}
    >
      <button
        ref={setActivatorNodeRef}
        type="button"
        aria-label={`Reorder ${song.title}`}
        className="flex h-full cursor-grab touch-none items-center justify-center text-muted-foreground/60 hover:text-foreground active:cursor-grabbing"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="size-4" />
      </button>
      <button type="button" onClick={onPlay} aria-label={`Play ${song.title}`} className="flex min-w-0 items-center gap-3 text-left">
        <CoverArt src={coverUrl(song.coverArt, 80)} alt="" className="size-10 rounded" />
        <span className="min-w-0">
          <span className={cn('block truncate font-medium', active && 'text-primary')}>{song.title}</span>
          <span className="block truncate text-xs text-muted-foreground">{song.artist}</span>
        </span>
      </button>
      <span className="hidden truncate text-xs text-muted-foreground md:block">{song.album}</span>
      <span className="text-right text-xs text-muted-foreground tabular-nums">{formatTime(song.duration)}</span>
      <TrackMenu
        item={{ kind: 'library', song }}
        label={label}
        onPlayNow={onPlay}
        extra={
          <DropdownMenuItem onSelect={onRemove}>
            <X /> Remove from this playlist
          </DropdownMenuItem>
        }
      />
    </li>
  )
}

function PlaylistTracks({ playlist }: { playlist: Playlist }) {
  const update = useUpdatePlaylist()
  const currentSongId = usePlayer((s) => {
    const cur = currentItem(s)
    return cur?.kind === 'library' ? cur.song.id : undefined
  })
  const rows: Row[] = playlist.songs.map((song, index) => ({ key: `${song.id}#${index}`, song, index }))
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return
    const from = rows.findIndex((r) => r.key === active.id)
    const to = rows.findIndex((r) => r.key === over.id)
    if (from < 0 || to < 0) return
    const songIds = arrayMove(playlist.songs, from, to).map((s) => s.id)
    update.mutate({ id: playlist.id, patch: { songIds } }, { onError: (err) => toast.error(failMessage(err, 'reorder')) })
  }

  const remove = (row: Row) =>
    update.mutate(
      { id: playlist.id, patch: { removeIndexes: [row.index] } },
      {
        onSuccess: () => toast.success(`Removed from ${playlist.name}`, { description: row.song.title }),
        onError: (err) => toast.error(failMessage(err, 'remove the track')),
      },
    )

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd} modifiers={[restrictToVerticalAxis]}>
      <SortableContext items={rows.map((r) => r.key)} strategy={verticalListSortingStrategy}>
        <ul aria-label={`${playlist.name} tracks`} className="flex flex-col">
          {rows.map((row) => (
            <SortableTrack
              key={row.key}
              row={row}
              active={row.song.id === currentSongId}
              onPlay={() => playSongs(playlist.songs, row.index, false)}
              onRemove={() => remove(row)}
            />
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  )
}

export function PlaylistView() {
  const { id = '' } = useParams()
  const { data: playlist, isPending, isError, error, refetch } = usePlaylist(id)
  const update = useUpdatePlaylist()
  const del = useDeletePlaylist()
  const navigate = useNavigate()
  const [renaming, setRenaming] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />
  if (isPending)
    return (
      <div>
        <PageHeaderSkeleton />
        <TrackListSkeleton rows={6} />
      </div>
    )

  const songs = playlist.songs
  const duration = songs.reduce((t, s) => t + s.duration, 0)
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        kicker="Playlist"
        title={playlist.name}
        cover={coverUrl(playlist.coverArt ?? songs[0]?.coverArt, 600)}
        meta={
          <span className="flex flex-wrap items-center gap-x-1.5">
            <span>{plural(songs.length, 'song')}</span>
            {duration > 0 ? (
              <span className="inline-flex items-center gap-1">
                · <Clock className="size-3.5" /> {formatTotal(duration)}
              </span>
            ) : null}
          </span>
        }
        actions={
          <>
            <Button size="lg" className="rounded-full px-6" disabled={songs.length === 0} onClick={() => playSongs(songs, 0, false)}>
              <Play className="fill-current" /> Play
            </Button>
            <Button
              size="lg"
              variant="secondary"
              className="rounded-full px-5"
              disabled={songs.length === 0}
              onClick={() => playSongs(songs, 0, true)}
            >
              <Shuffle /> Shuffle
            </Button>
            <Button variant="ghost" size="icon" aria-label="Rename playlist" onClick={() => setRenaming(true)}>
              <Pencil />
            </Button>
            <Button variant="ghost" size="icon" aria-label="Delete playlist" onClick={() => setConfirmDelete(true)}>
              <Trash2 />
            </Button>
          </>
        }
      />
      {songs.length === 0 ? (
        <EmptyState icon={<ListMusic />} title="This playlist is empty">
          Use “Add to playlist” in any track menu to fill it.
        </EmptyState>
      ) : (
        <PlaylistTracks playlist={playlist} />
      )}

      <NameDialog
        open={renaming}
        onOpenChange={setRenaming}
        title="Rename playlist"
        initial={playlist.name}
        submitLabel="Save"
        pending={update.isPending}
        onSubmit={(name) => {
          setRenaming(false)
          if (name !== playlist.name)
            update.mutate({ id: playlist.id, patch: { name } }, { onError: (err) => toast.error(failMessage(err, 'rename')) })
        }}
      />
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogTitle>Delete “{playlist.name}”?</DialogTitle>
          <DialogDescription>This removes it from your library for every player. The songs stay.</DialogDescription>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={del.isPending}
              onClick={() =>
                del.mutate(playlist.id, {
                  onSuccess: () => {
                    setConfirmDelete(false)
                    toast.success(`Deleted "${playlist.name}"`)
                    void navigate('/playlists')
                  },
                  onError: (err) => toast.error(failMessage(err, 'delete the playlist')),
                })
              }
            >
              Delete
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export function LikedView() {
  const { data: songs, isPending, isError, error, refetch } = useStarred()
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />
  if (isPending)
    return (
      <div>
        <PageHeaderSkeleton />
        <TrackListSkeleton rows={6} />
      </div>
    )
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        kicker="Playlist"
        title="Liked Songs"
        cover={coverUrl(songs[0]?.coverArt, 600)}
        meta={<span>{plural(songs.length, 'song')}</span>}
        actions={
          <>
            <Button size="lg" className="rounded-full px-6" disabled={songs.length === 0} onClick={() => playSongs(songs, 0, false)}>
              <Play className="fill-current" /> Play
            </Button>
            <Button
              size="lg"
              variant="secondary"
              className="rounded-full px-5"
              disabled={songs.length === 0}
              onClick={() => playSongs(songs, 0, true)}
            >
              <Shuffle /> Shuffle
            </Button>
          </>
        }
      />
      {songs.length === 0 ? (
        <EmptyState icon={<Heart />} title="No liked songs yet">
          Tap the heart in the player, or “Like” in any track menu.
        </EmptyState>
      ) : (
        <TrackList songs={songs} />
      )}
    </div>
  )
}
