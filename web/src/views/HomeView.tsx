import { useAlbumList } from '@/api/hooks'
import type { AlbumListType } from '@/api/types'
import { AlbumCard } from '@/components/music/AlbumCard'
import { CardRow, CardSkeletons } from '@/components/music/CardGrid'
import { LibraryEmpty } from '@/components/states/LibraryEmpty'
import { ErrorState, SectionHeader } from '@/components/states/States'

const ROWS: { type: AlbumListType; title: string }[] = [
  { type: 'recent', title: 'Recently played' },
  { type: 'newest', title: 'Newly added' },
  { type: 'random', title: 'Rediscover' },
]

function greeting(): string {
  const h = new Date().getHours()
  if (h < 5) return 'Late night listening'
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

function AlbumRowSection({ type, title }: { type: AlbumListType; title: string }) {
  const { data, isPending, isError } = useAlbumList(type, 20)
  if (isError || (data && data.length === 0)) return null
  return (
    <section>
      <SectionHeader title={title} />
      <CardRow>{isPending ? <CardSkeletons count={6} /> : data.map((a) => <AlbumCard key={a.id} album={a} />)}</CardRow>
    </section>
  )
}

export function HomeView() {
  // "newest" decides empty/offline for the whole page; the rows share its cache semantics.
  const probe = useAlbumList('newest', 20)

  return (
    <div className="flex flex-col gap-8">
      <header className="pt-2">
        <h1 className="text-2xl font-bold tracking-tight md:text-3xl">{greeting()}</h1>
      </header>
      {probe.isError ? (
        <ErrorState error={probe.error} onRetry={() => void probe.refetch()} />
      ) : probe.data && probe.data.length === 0 ? (
        <LibraryEmpty />
      ) : (
        ROWS.map((r) => <AlbumRowSection key={r.type} {...r} />)
      )}
    </div>
  )
}
