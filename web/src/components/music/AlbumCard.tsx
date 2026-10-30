import { Play } from 'lucide-react'
import { Link } from 'react-router'
import { coverUrl } from '@/api/client'
import type { AlbumSummary } from '@/api/types'
import { usePlayAlbum } from '@/player/usePlayAlbum'
import { CoverArt } from './CoverArt'

export function AlbumCard({ album, showArtist = true }: { album: AlbumSummary; showArtist?: boolean }) {
  const play = usePlayAlbum()

  const playAlbum = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    void play(album.id)
  }

  return (
    <Link
      to={`/album/${encodeURIComponent(album.id)}`}
      className="group block w-full rounded-lg p-2 transition-colors outline-none hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="relative">
        <CoverArt src={coverUrl(album.coverArt, 300)} alt={`${album.name} cover`} className="w-full shadow-md shadow-black/20" />
        <button
          type="button"
          onClick={playAlbum}
          aria-label={`Play ${album.name}`}
          className="absolute right-2 bottom-2 flex size-10 translate-y-1 items-center justify-center rounded-full bg-primary text-primary-foreground opacity-0 shadow-lg transition-all group-hover:translate-y-0 group-hover:opacity-100 focus-visible:translate-y-0 focus-visible:opacity-100"
        >
          <Play className="size-4 fill-current" />
        </button>
      </div>
      <div className="mt-2 min-w-0">
        <div className="truncate text-sm font-medium">{album.name}</div>
        <div className="truncate text-xs text-muted-foreground">
          {showArtist ? album.artist : null}
          {showArtist && album.year ? ' · ' : null}
          {album.year ?? null}
        </div>
      </div>
    </Link>
  )
}
