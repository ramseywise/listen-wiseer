import { useArtists } from '@/api/hooks'
import { ArtistCard } from '@/components/music/ArtistCard'
import { CardGrid, CardSkeletons } from '@/components/music/CardGrid'
import { LibraryEmpty } from '@/components/states/LibraryEmpty'
import { ErrorState } from '@/components/states/States'
import { plural } from '@/lib/format'

export function LibraryView() {
  const { data, isPending, isError, error, refetch } = useArtists()
  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-baseline justify-between gap-4 pt-2">
        <h1 className="text-2xl font-bold tracking-tight md:text-3xl">Library</h1>
        {data && data.length > 0 ? (
          <span className="text-sm text-muted-foreground">{plural(data.length, 'artist')}</span>
        ) : null}
      </header>
      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <CardGrid>
          <CardSkeletons count={10} round />
        </CardGrid>
      ) : data.length === 0 ? (
        <LibraryEmpty />
      ) : (
        <CardGrid>
          {data.map((a) => (
            <ArtistCard key={a.id} artist={a} />
          ))}
        </CardGrid>
      )}
    </div>
  )
}
