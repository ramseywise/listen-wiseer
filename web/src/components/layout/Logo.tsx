import { cn } from '@/lib/utils'

/** listen-wiseer mark: an ear-like arc around three ascending bars. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn('size-7', className)}>
      <defs>
        <linearGradient id="lw-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--primary)" />
          <stop offset="1" stopColor="var(--violet)" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#lw-mark)" />
      <path d="M9 21.5a9 9 0 1 1 14 0" fill="none" stroke="var(--primary-foreground)" strokeWidth="2.2" strokeLinecap="round" opacity=".9" />
      <rect x="12" y="16" width="2.2" height="7" rx="1.1" fill="var(--primary-foreground)" />
      <rect x="15" y="13" width="2.2" height="10" rx="1.1" fill="var(--primary-foreground)" />
      <rect x="18" y="15" width="2.2" height="8" rx="1.1" fill="var(--primary-foreground)" />
    </svg>
  )
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      {compact ? null : (
        <span className="text-[15px] font-semibold tracking-tight">
          listen<span className="text-primary">-</span>wiseer
        </span>
      )}
    </div>
  )
}
