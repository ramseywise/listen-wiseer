import { Clock, Play, Shuffle } from 'lucide-react'
import { Link, useParams } from 'react-router'
import { coverUrl } from '@/api/client'
import { useAlbum } from '@/api/hooks'
import { PageHeader, PageHeaderSkeleton } from '@/components/music/PageHeader'
import { TrackList, TrackListSkeleton } from '@/components/music/TrackList'
import { EmptyState, ErrorState } from '@/components/states/States'
import { Button } from '@/components/ui/button'
import { formatTotal, plural } from '@/lib/format'
import { playSongs } from '@/player/usePlayAlbum'

export function AlbumView() {
  const { id = '' } = useParams()
  const { data: album, isPending, isError, error, refetch } = useAlbum(id)

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />
  if (isPending)
    return (
      <div>
        <PageHeaderSkeleton />
        <TrackListSkeleton rows={8} />
      </div>
    )

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        kicker="Album"
        title={album.name}
        cover={coverUrl(album.coverArt, 600)}
        meta={
          <span className="flex flex-wrap items-center gap-x-1.5">
            <Link to={`/artist/${encodeURIComponent(album.artistId)}`} className="font-medium text-foreground hover:underline">
              {album.artist}
            </Link>
            {album.year ? <span>· {album.year}</span> : null}
            <span>· {plural(album.songCount, 'song')}</span>
            <span className="inline-flex items-center gap-1">
              · <Clock className="size-3.5" /> {formatTotal(album.duration)}
            </span>
          </span>
        }
        actions={
          <>
            <Button
              size="lg"
              className="rounded-full px-6"
              disabled={album.songs.length === 0}
              onClick={() => playSongs(album.songs, 0, false)}
            >
              <Play className="fill-current" /> Play
            </Button>
            <Button
              size="lg"
              variant="secondary"
              className="rounded-full px-5"
              disabled={album.songs.length === 0}
              onClick={() => playSongs(album.songs, 0, true)}
            >
              <Shuffle /> Shuffle
            </Button>
          </>
        }
      />
      {album.songs.length === 0 ? (
        <EmptyState icon={<Play />} title="No tracks on this album" />
      ) : (
        <TrackList songs={album.songs} variant="album" />
      )}
    </div>
  )
}
