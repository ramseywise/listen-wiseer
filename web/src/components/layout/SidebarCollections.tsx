import { ChevronRight, Plus } from 'lucide-react'
import { useState } from 'react'
import { NavLink } from 'react-router'
import { useArchivePlaylists, usePlaylists } from '@/api/collections'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { openNewPlaylist } from '@/playlists/newPlaylist'

const rowClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'flex items-center justify-between gap-2 rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent/60 hover:text-foreground',
    isActive && 'bg-accent text-foreground',
  )

/** The user's Navidrome playlists (wide sidebar only). */
export function SidebarPlaylists() {
  const { data } = usePlaylists()
  return (
    <section aria-label="Your playlists" className="flex flex-col gap-0.5">
      <div className="flex items-center justify-between px-3">
        <span className="text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase">Your playlists</span>
        <Button variant="ghost" size="icon-xs" aria-label="New playlist" onClick={() => openNewPlaylist()}>
          <Plus />
        </Button>
      </div>
      {data?.map((p) => (
        <NavLink key={p.id} to={`/playlist/${encodeURIComponent(p.id)}`} className={rowClass}>
          <span className="truncate">{p.name}</span>
        </NavLink>
      ))}
    </section>
  )
}

/** Archived Spotify-era playlists with track counts, collapsed by default (there are ~80). */
export function SidebarArchive() {
  const [open, setOpen] = useState(false)
  const { data } = useArchivePlaylists()
  return (
    <section aria-label="Archive playlists" className="flex flex-col gap-0.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 px-3 py-1 text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase hover:text-foreground"
      >
        <ChevronRight className={cn('size-3.5 transition-transform', open && 'rotate-90')} />
        Archive{data ? ` (${data.length})` : ''}
      </button>
      {open
        ? data?.map((p) => (
            <NavLink key={p.id} to={`/archive/${encodeURIComponent(p.id)}`} className={rowClass}>
              <span className="truncate">{p.name}</span>
              <span className="shrink-0 text-xs tabular-nums">{p.trackCount}</span>
            </NavLink>
          ))
        : null}
    </section>
  )
}
