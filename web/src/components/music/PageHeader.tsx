import type { ReactNode } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { CoverArt } from './CoverArt'

type Props = {
  kicker: string
  title: string
  cover: string | undefined
  round?: boolean
  meta?: ReactNode
  actions?: ReactNode
}

export function PageHeader({ kicker, title, cover, round = false, meta, actions }: Props) {
  return (
    <header className="relative -mx-4 -mt-4 overflow-hidden px-4 pt-8 pb-6 md:-mx-8 md:-mt-6 md:px-8 md:pt-12">
      {cover ? (
        <img
          src={cover}
          alt=""
          aria-hidden
          className="pointer-events-none absolute inset-0 size-full scale-125 object-cover opacity-25 blur-3xl"
        />
      ) : null}
      <div className="absolute inset-0 bg-gradient-to-b from-transparent to-background" />
      <div className="relative flex flex-col items-start gap-5 sm:flex-row sm:items-end">
        <CoverArt
          src={cover}
          alt={title}
          rounded={round ? 'full' : 'lg'}
          className={cn('w-40 shadow-2xl shadow-black/40 md:w-52')}
        />
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">{kicker}</div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight break-words md:text-5xl">{title}</h1>
          {meta ? <div className="mt-3 text-sm text-muted-foreground">{meta}</div> : null}
          {actions ? <div className="mt-5 flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
      </div>
    </header>
  )
}

export function PageHeaderSkeleton({ round = false }: { round?: boolean }) {
  return (
    <div className="flex flex-col items-start gap-5 pt-4 pb-6 sm:flex-row sm:items-end" aria-hidden>
      <Skeleton className={cn('size-40 md:size-52', round ? 'rounded-full' : 'rounded-lg')} />
      <div className="flex-1 space-y-3">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-3.5 w-1/3" />
      </div>
    </div>
  )
}
