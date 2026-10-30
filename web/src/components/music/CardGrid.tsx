import type { ReactNode } from 'react'
import { Skeleton } from '@/components/ui/skeleton'

export function CardGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-1 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">{children}</div>
}

/** Horizontal, scroll-snapping row used on Home. */
export function CardRow({ children }: { children: ReactNode }) {
  return (
    <div className="scrollbar-thin -mx-2 flex snap-x gap-1 overflow-x-auto pb-2 [&>*]:w-40 [&>*]:shrink-0 [&>*]:snap-start sm:[&>*]:w-44">
      {children}
    </div>
  )
}

export function CardSkeletons({ count = 6, round = false }: { count?: number; round?: boolean }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="p-2" aria-hidden>
          <Skeleton className={round ? 'aspect-square w-full rounded-full' : 'aspect-square w-full rounded-md'} />
          <Skeleton className="mt-2 h-3.5 w-3/4" />
          <Skeleton className="mt-1.5 h-3 w-1/2" />
        </div>
      ))}
    </>
  )
}
