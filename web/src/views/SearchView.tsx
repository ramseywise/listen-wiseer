import { Loader2, Search as SearchIcon, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router'
import { useSearch } from '@/api/hooks'
import { AlbumCard } from '@/components/music/AlbumCard'
import { ArtistCard } from '@/components/music/ArtistCard'
import { CardGrid } from '@/components/music/CardGrid'
import { TrackList, TrackListSkeleton } from '@/components/music/TrackList'
import { EmptyState, ErrorState, SectionHeader } from '@/components/states/States'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'

export function SearchView() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const debounced = useDebouncedValue(q, 250)
  const { data, isFetching, isPending, isError, error, refetch } = useSearch(debounced, 20)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const setQ = (value: string) => setParams(value ? { q: value } : {}, { replace: true })
  const hasQuery = debounced.trim().length > 0
  const total = data ? data.artists.length + data.albums.length + data.songs.length : 0

  return (
    <div className="flex flex-col gap-6">
      <div className="relative max-w-xl">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          ref={inputRef}
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Artists, albums or songs"
          aria-label="Search library"
          className="h-11 w-full rounded-full border bg-surface-raised pr-10 pl-10 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-search-cancel-button]:hidden"
        />
        {isFetching && hasQuery ? (
          <Loader2 className="absolute top-1/2 right-3.5 size-4 -translate-y-1/2 animate-spin text-muted-foreground" />
        ) : q ? (
          <button
            type="button"
            onClick={() => setQ('')}
            aria-label="Clear search"
            className="absolute top-1/2 right-3 -translate-y-1/2 rounded-full p-0.5 text-muted-foreground hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        ) : null}
      </div>

      {!hasQuery ? (
        <EmptyState icon={<SearchIcon />} title="Search your library">
          Find artists, albums and tracks across everything Navidrome has scanned.
        </EmptyState>
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <TrackListSkeleton rows={5} />
      ) : total === 0 ? (
        <EmptyState icon={<SearchIcon />} title={`No results for “${debounced}”`}>
          Check the spelling, or try an artist or album name.
        </EmptyState>
      ) : (
        <>
          {data.songs.length > 0 ? (
            <section>
              <SectionHeader title="Songs" />
              <TrackList songs={data.songs.slice(0, 10)} />
            </section>
          ) : null}
          {data.artists.length > 0 ? (
            <section>
              <SectionHeader title="Artists" />
              <CardGrid>
                {data.artists.map((a) => (
                  <ArtistCard key={a.id} artist={a} />
                ))}
              </CardGrid>
            </section>
          ) : null}
          {data.albums.length > 0 ? (
            <section>
              <SectionHeader title="Albums" />
              <CardGrid>
                {data.albums.map((a) => (
                  <AlbumCard key={a.id} album={a} />
                ))}
              </CardGrid>
            </section>
          ) : null}
        </>
      )}
    </div>
  )
}
