import { Play, Radio, Shuffle } from 'lucide-react'
import { useState } from 'react'
import { useParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, coverUrl } from '@/api/client'
import { queryKeys, useArtist } from '@/api/hooks'
import type { Song } from '@/api/types'
import { AlbumCard } from '@/components/music/AlbumCard'
import { CardGrid, CardSkeletons } from '@/components/music/CardGrid'
import { PageHeader, PageHeaderSkeleton } from '@/components/music/PageHeader'
import { EmptyState, ErrorState, SectionHeader } from '@/components/states/States'
import { Button } from '@/components/ui/button'
import { plural } from '@/lib/format'
import { playSongs } from '@/player/usePlayAlbum'
import { startRadio } from '@/radio/startRadio'

export function ArtistView() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const { data: artist, isPending, isError, error, refetch } = useArtist(id)
  const [loadingAll, setLoadingAll] = useState(false)

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />
  if (isPending)
    return (
      <div>
        <PageHeaderSkeleton round />
        <CardGrid>
          <CardSkeletons count={5} />
        </CardGrid>
      </div>
    )

  // Newest first on the page; "play all" goes oldest → newest.
  const albums = [...artist.albums].sort((a, b) => (b.year ?? 0) - (a.year ?? 0))

  const playAll = async (shuffle: boolean) => {
    setLoadingAll(true)
    try {
      const full = await Promise.all(
        [...albums].reverse().map((a) =>
          qc.fetchQuery({ queryKey: queryKeys.album(a.id), queryFn: ({ signal }) => api.album(a.id, signal) }),
        ),
      )
      const songs: Song[] = full.flatMap((a) => a.songs)
      playSongs(songs, 0, shuffle)
    } catch {
      toast.error(`Couldn't load ${artist.name}'s albums`)
    } finally {
      setLoadingAll(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        kicker="Artist"
        title={artist.name}
        round
        cover={coverUrl(artist.coverArt, 600)}
        meta={plural(artist.albumCount, 'album')}
        actions={
          albums.length > 0 ? (
            <>
              <Button size="lg" className="rounded-full px-6" disabled={loadingAll} onClick={() => void playAll(false)}>
                <Play className="fill-current" /> Play
              </Button>
              <Button size="lg" variant="secondary" className="rounded-full px-5" disabled={loadingAll} onClick={() => void playAll(true)}>
                <Shuffle /> Shuffle
              </Button>
              <Button size="lg" variant="outline" className="rounded-full px-5" onClick={() => void startRadio({ artist: artist.name }, artist.name)}>
                <Radio /> Start radio
              </Button>
            </>
          ) : null
        }
      />
      <section>
        <SectionHeader title="Discography" />
        {albums.length === 0 ? (
          <EmptyState icon={<Play />} title="No albums yet" />
        ) : (
          <CardGrid>
            {albums.map((a) => (
              <AlbumCard key={a.id} album={a} showArtist={false} />
            ))}
          </CardGrid>
        )}
      </section>
    </div>
  )
}
