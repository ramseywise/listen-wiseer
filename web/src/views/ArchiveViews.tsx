import { Archive, CopyPlus, ExternalLink, Loader2, Play, Shuffle } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'
import { isLibraryOffline } from '@/api/client'
import { useArchivePlaylist, useArchivePlaylists, useCopyArchive } from '@/api/collections'
import type { ArchiveCopyResult, ArchivePlaylist, ArchiveTrack } from '@/api/types'
import { archiveFeeder, useResolution } from '@/archive/feeder'
import { PageHeader, PageHeaderSkeleton } from '@/components/music/PageHeader'
import { TrackListSkeleton } from '@/components/music/TrackList'
import { EmptyState, ErrorState } from '@/components/states/States'
import { Button } from '@/components/ui/button'
import { plural } from '@/lib/format'
import { cn } from '@/lib/utils'

export function ArchiveIndexView() {
  const { data, isPending, isError, error, refetch } = useArchivePlaylists()
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Archive</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Spotify-era playlists, kept read-only. Play them from your library or as previews, or copy one into your
          library.
        </p>
      </div>
      {isPending ? <TrackListSkeleton rows={8} /> : null}
      {data?.length === 0 ? <EmptyState icon={<Archive />} title="No archived playlists" /> : null}
      <ul className="flex flex-col">
        {data?.map((p) => (
          <li key={p.id}>
            <Link
              to={`/archive/${encodeURIComponent(p.id)}`}
              className="flex h-12 items-center justify-between gap-3 rounded-md px-2 text-sm hover:bg-accent/60"
            >
              <span className="truncate font-medium">{p.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{plural(p.trackCount, 'track')}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

function youtubeSearch(t: ArchiveTrack): string {
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(`${t.artist} ${t.title}`)}`
}

function ResolutionBadge({ track }: { track: ArchiveTrack }) {
  const r = useResolution(track)
  if (!r) return null
  if (r.status === 'pending') return <Loader2 aria-label="Finding" className="size-3.5 animate-spin text-muted-foreground" />
  if (r.status === 'error') return <span className="text-[10px] text-muted-foreground uppercase">unavailable</span>
  const p = r.playable
  if (p.song) return <span className="rounded bg-primary/15 px-1.5 text-[10px] text-primary uppercase">library</span>
  if (p.previewUrl) return <span className="rounded bg-muted px-1.5 text-[10px] uppercase">preview</span>
  return (
    <a
      href={p.youtubeUrl ?? youtubeSearch(track)}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground hover:underline"
    >
      YouTube <ExternalLink className="size-3" />
    </a>
  )
}

function ArchiveRow({ track, position, onPlay }: { track: ArchiveTrack; position: number; onPlay: () => void }) {
  return (
    <li
      data-testid="archive-row"
      onDoubleClick={onPlay}
      className="group grid h-14 grid-cols-[2rem_1fr_auto] items-center gap-3 rounded-md px-2 text-sm hover:bg-accent/60"
    >
      <div className="relative flex size-8 items-center justify-center text-muted-foreground tabular-nums">
        <span className="group-hover:invisible">{position + 1}</span>
        <button
          type="button"
          aria-label={`Play ${track.title}`}
          onClick={onPlay}
          className="invisible absolute inset-0 flex items-center justify-center text-foreground group-hover:visible focus-visible:visible"
        >
          <Play className="size-4 fill-current" />
        </button>
      </div>
      <div className="min-w-0">
        <div className="truncate font-medium">{track.title}</div>
        <div className="truncate text-xs text-muted-foreground">{track.artist}</div>
      </div>
      <ResolutionBadge track={track} />
    </li>
  )
}

function CopyNote({ result }: { result: ArchiveCopyResult }) {
  const n = result.unmatched.length
  return (
    <div className="rounded-lg border bg-surface px-4 py-3 text-sm" role="status">
      Copied to{' '}
      <Link to={`/playlist/${encodeURIComponent(result.playlist.id)}`} className="font-medium text-primary hover:underline">
        {result.playlist.name}
      </Link>{' '}
      with {plural(result.playlist.songCount, 'track')}.{' '}
      {n > 0 ? (
        <details className="mt-1 inline">
          <summary className="cursor-pointer text-muted-foreground">{plural(n, 'track')} not in your library</summary>
          <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
            {result.unmatched.map((t, i) => (
              <li key={i}>
                {t.artist} — {t.title}
              </li>
            ))}
          </ul>
        </details>
      ) : (
        <span className="text-muted-foreground">Every track matched.</span>
      )}
    </div>
  )
}

async function startArchive(playlist: ArchivePlaylist, opts: { startIndex?: number; shuffle?: boolean }) {
  try {
    const ok = await archiveFeeder.play(playlist, opts)
    if (!ok) toast.error('Nothing playable here', { description: 'No library match or preview for these tracks.' })
  } catch {
    toast.error("Couldn't start the playlist")
  }
}

export function ArchivePlaylistView() {
  const { id = '' } = useParams()
  const { data: playlist, isPending, isError, error, refetch } = useArchivePlaylist(id)
  const copy = useCopyArchive()
  const [copied, setCopied] = useState<ArchiveCopyResult | null>(null)

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />
  if (isPending)
    return (
      <div>
        <PageHeaderSkeleton />
        <TrackListSkeleton rows={8} />
      </div>
    )

  const empty = playlist.tracks.length === 0
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        kicker="Archived playlist"
        title={playlist.name}
        cover={undefined}
        meta={<span>{plural(playlist.tracks.length, 'track')} · read-only</span>}
        actions={
          <>
            <Button size="lg" className="rounded-full px-6" disabled={empty} onClick={() => void startArchive(playlist, {})}>
              <Play className="fill-current" /> Play
            </Button>
            <Button
              size="lg"
              variant="secondary"
              className="rounded-full px-5"
              disabled={empty}
              onClick={() => void startArchive(playlist, { shuffle: true })}
            >
              <Shuffle /> Shuffle
            </Button>
            <Button
              variant="outline"
              className={cn('rounded-full')}
              disabled={empty || copy.isPending}
              onClick={() =>
                copy.mutate(
                  { id: playlist.id },
                  {
                    onSuccess: (result) => {
                      setCopied(result)
                      toast.success(`Copied to "${result.playlist.name}"`, {
                        description: result.unmatched.length
                          ? `${plural(result.unmatched.length, 'track')} not in your library`
                          : 'Every track matched',
                      })
                    },
                    onError: (err) => toast.error(isLibraryOffline(err) ? 'Library is offline' : "Couldn't copy the playlist"),
                  },
                )
              }
            >
              {copy.isPending ? <Loader2 className="animate-spin" /> : <CopyPlus />} Copy to library playlist
            </Button>
          </>
        }
      />
      {copied ? <CopyNote result={copied} /> : null}
      {empty ? (
        <EmptyState icon={<Archive />} title="No tracks in this playlist" />
      ) : (
        <ul aria-label={`${playlist.name} tracks`} className="flex flex-col">
          {playlist.tracks.map((t, i) => (
            <ArchiveRow key={i} track={t} position={i} onPlay={() => void startArchive(playlist, { startIndex: i })} />
          ))}
        </ul>
      )}
    </div>
  )
}
