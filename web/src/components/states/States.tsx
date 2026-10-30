import { CloudOff, RefreshCw, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { isLibraryOffline } from '@/api/client'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type EmptyProps = {
  icon: ReactNode
  title: string
  children?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon, title, children, action, className }: EmptyProps) {
  return (
    <div
      className={cn(
        'mx-auto flex max-w-md flex-col items-center px-6 py-14 text-center',
        className,
      )}
    >
      <div className="mb-5 flex size-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-violet/20 text-primary ring-1 ring-primary/20 [&_svg]:size-7">
        {icon}
      </div>
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      {children ? <div className="mt-2 text-sm leading-relaxed text-muted-foreground">{children}</div> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  )
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const offline = isLibraryOffline(error)
  return (
    <EmptyState
      className={className}
      icon={offline ? <CloudOff /> : <TriangleAlert />}
      title={offline ? 'Library offline' : 'Something went wrong'}
      action={
        onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw /> Try again
          </Button>
        ) : null
      }
    >
      {offline ? (
        <>
          Can&apos;t reach the music library right now. Check that the API and Navidrome are running, then
          try again.
        </>
      ) : (
        <>{error instanceof Error ? error.message : 'An unexpected error occurred.'}</>
      )}
    </EmptyState>
  )
}

export function SectionHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-2 flex items-end justify-between gap-4">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      {children}
    </div>
  )
}
