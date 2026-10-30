import { Link } from 'react-router'
import { coverUrl } from '@/api/client'
import type { ArtistSummary } from '@/api/types'
import { plural } from '@/lib/format'
import { CoverArt } from './CoverArt'

export function ArtistCard({ artist }: { artist: ArtistSummary }) {
  return (
    <Link
      to={`/artist/${encodeURIComponent(artist.id)}`}
      className="group block rounded-lg p-2 text-center transition-colors outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring"
    >
      <CoverArt src={coverUrl(artist.coverArt, 300)} alt={artist.name} rounded="full" className="mx-auto w-full shadow-md shadow-black/20" />
      <div className="mt-2 truncate text-sm font-medium">{artist.name}</div>
      <div className="text-xs text-muted-foreground">{plural(artist.albumCount, 'album')}</div>
    </Link>
  )
}
