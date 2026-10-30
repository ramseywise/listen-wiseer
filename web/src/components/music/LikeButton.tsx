import { Heart } from 'lucide-react'
import { toast } from 'sonner'
import { isLibraryOffline } from '@/api/client'
import { useIsStarred, useToggleStar } from '@/api/collections'
import type { Song } from '@/api/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function LikeButton({ song, className }: { song: Song; className?: string }) {
  const starred = useIsStarred(song)
  const toggle = useToggleStar()
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={starred ? `Unlike ${song.title}` : `Like ${song.title}`}
      aria-pressed={starred}
      className={cn('size-8 shrink-0 text-muted-foreground hover:text-foreground', starred && 'text-primary hover:text-primary', className)}
      onClick={() =>
        toggle.mutate(
          { song, star: !starred },
          { onError: (err) => toast.error(isLibraryOffline(err) ? 'Library is offline' : "Couldn't update likes") },
        )
      }
    >
      <Heart className={cn(starred && 'fill-current')} />
    </Button>
  )
}
