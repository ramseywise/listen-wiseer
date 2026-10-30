import { Disc3 } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'

type Props = {
  src: string | undefined
  alt: string
  className?: string
  rounded?: 'md' | 'lg' | 'full'
}

export function CoverArt({ src, alt, className, rounded = 'md' }: Props) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  const radius = rounded === 'full' ? 'rounded-full' : rounded === 'lg' ? 'rounded-lg' : 'rounded-md'
  const showImg = src !== undefined && failedSrc !== src
  return (
    <div
      className={cn(
        'relative aspect-square shrink-0 overflow-hidden bg-gradient-to-br from-secondary to-muted',
        radius,
        className,
      )}
    >
      {showImg ? (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setFailedSrc(src)}
          className="size-full object-cover"
        />
      ) : (
        <div className="flex size-full items-center justify-center text-muted-foreground/60" aria-label={alt} role="img">
          <Disc3 className="size-1/3" strokeWidth={1.25} />
        </div>
      )}
    </div>
  )
}
