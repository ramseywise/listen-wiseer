import { useQueryClient } from '@tanstack/react-query'
import { Compass, Download, ListEnd, Loader2, Play, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { api } from '@/api/client'
import { queryKeys, useDiscover } from '@/api/hooks'
import type { DiscoverSection, RadioTrack } from '@/api/types'
import { archiveFeeder, playableToItem } from '@/archive/feeder'
import { CoverArt } from '@/components/music/CoverArt'
import { TrackListSkeleton } from '@/components/music/TrackList'
import { EmptyState, ErrorState, SectionHeader } from '@/components/states/States'
import { Button } from '@/components/ui/button'
import { usePlayer } from '@/player/playerStore'
import type { QueueItemInput } from '@/player/queue'

const SOURCE_LABEL: Record<string, string> = { archive_org: 'Internet Archive', jamendo: 'Jamendo' }

/** Library tracks come back playable; the rest resolve through /api/playable on demand. */
async function toItem(t: RadioTrack): Promise<QueueItemInput | null> {
  const playable = t.playable ?? (await api.playable(t))
  return playableToItem(playable)
}

function FreeLink({ track }: { track: RadioTrack }) {
  const free = track.free
  if (!free) return null
  // TODO(2): no HTTP download route yet (download_track is agent-only) — link to the source page.
  return (
    <a
      href={free.pageUrl ?? free.downloadUrl}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground"
      title={free.licenseUrl ? `Licence: ${free.licenseUrl}` : undefined}
    >
      <Download className="size-3" /> {SOURCE_LABEL[free.source] ?? free.source}
    </a>
  )
}

function DiscoverRow({ track }: { track: RadioTrack }) {
  const [busy, setBusy] = useState(false)
  const label = `${track.title} — ${track.artist}`

  const run = async (mode: 'play' | 'queue') => {
    setBusy(true)
    try {
      const item = await toItem(track)
      if (!item) {
        toast.error('Not playable here', { description: `${label} isn't in your library and has no preview.` })
        return
      }
      if (mode === 'play') usePlayer.getState().playNow([item])
      else {
        usePlayer.getState().addToQueue([item])
        toast.success('Added to queue', { description: label })
      }
    } catch {
      toast.error("Couldn't look that track up")
    } finally {
      setBusy(false)
    }
  }

  return (
    <li
      data-testid="discover-row"
      className="group grid h-14 grid-cols-[2.5rem_1fr_auto] items-center gap-3 rounded-md px-2 text-sm hover:bg-accent/60"
      onDoubleClick={() => void run('play')}
    >
      <CoverArt src={track.playable?.coverUrl} alt="" className="size-10 rounded" />
      <div className="min-w-0">
        <div className="truncate font-medium">{track.title}</div>
        <div className="truncate text-xs text-muted-foreground">
          {track.artist}
          {track.reason ? <span className="text-muted-foreground/70"> · {track.reason}</span> : null}
        </div>
      </div>
      <div className="flex items-center gap-1">
        <FreeLink track={track} />
        {track.source === 'library' ? (
          <span className="rounded bg-primary/15 px-1.5 text-[10px] text-primary uppercase max-sm:hidden">library</span>
        ) : null}
        <Button variant="ghost" size="icon" className="size-8" aria-label={`Play ${label}`} disabled={busy} onClick={() => void run('play')}>
          {busy ? <Loader2 className="animate-spin" /> : <Play className="fill-current" />}
        </Button>
        <Button variant="ghost" size="icon" className="size-8" aria-label={`Add ${label} to queue`} disabled={busy} onClick={() => void run('queue')}>
          <ListEnd />
        </Button>
      </div>
    </li>
  )
}

function Section({ section }: { section: DiscoverSection }) {
  const playAll = async () => {
    const ok = await archiveFeeder
      .play({ id: `discover:${section.id}`, name: section.title, tracks: section.tracks })
      .catch(() => false)
    if (!ok) toast.error('Nothing playable here', { description: 'No library match or preview for these tracks.' })
  }
  return (
    <section aria-label={section.title} className="flex flex-col gap-1">
      <SectionHeader title={section.title}>
        {section.tracks.length > 0 ? (
          <Button variant="ghost" size="sm" onClick={() => void playAll()}>
            <Play className="fill-current" /> Play all
          </Button>
        ) : null}
      </SectionHeader>
      {section.tracks.length === 0 ? (
        <p className="px-2 py-3 text-sm text-muted-foreground">Nothing here right now.</p>
      ) : (
        <ul className="flex flex-col">
          {section.tracks.map((t) => (
            <DiscoverRow key={`${t.artist}\u0000${t.title}`} track={t} />
          ))}
        </ul>
      )}
    </section>
  )
}

export function DiscoverView() {
  const { data, isPending, isError, error, refetch } = useDiscover()
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)

  const refresh = async () => {
    setRefreshing(true)
    try {
      queryClient.setQueryData(queryKeys.discover, await api.discover(true))
    } catch {
      toast.error("Couldn't refresh Discover")
    } finally {
      setRefreshing(false)
    }
  }

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />
  const empty = data !== undefined && data.sections.every((s) => s.tracks.length === 0)
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Discover</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Unplayed corners of your library, artists new to you, and free legal downloads.
          </p>
        </div>
        <Button variant="outline" size="sm" disabled={refreshing || isPending} onClick={() => void refresh()}>
          {refreshing ? <Loader2 className="animate-spin" /> : <RefreshCw />} Refresh
        </Button>
      </div>
      {isPending ? (
        <>
          <p className="text-sm text-muted-foreground">Asking around — this can take a few seconds…</p>
          <TrackListSkeleton rows={6} />
        </>
      ) : null}
      {empty ? <EmptyState icon={<Compass />} title="Nothing to discover yet">Play a few things, or like some songs, and check back.</EmptyState> : null}
      {data?.sections.map((s) => <Section key={s.id} section={s} />)}
    </div>
  )
}
