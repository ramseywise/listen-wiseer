import { FolderOpen } from 'lucide-react'
import { EmptyState } from './States'

/** The real current state: Navidrome is up but has nothing scanned yet. */
export function LibraryEmpty({ compact = false }: { compact?: boolean }) {
  return (
    <EmptyState icon={<FolderOpen />} title="Your library is ready for music" className={compact ? 'py-8' : undefined}>
      <p>
        Nothing has been scanned yet. Drop audio files into your music folder
        (<code className="rounded bg-muted px-1 py-0.5 text-xs">data/library/</code> or{' '}
        <code className="rounded bg-muted px-1 py-0.5 text-xs">$MUSIC_DIR</code>) and Navidrome will pick
        them up on its next scan.
      </p>
      {compact ? null : (
        <p className="mt-3">Free, legal downloads from Jamendo and the Internet Archive land there too.</p>
      )}
    </EmptyState>
  )
}
