import { Slider as SliderPrimitive } from 'radix-ui'
import { useState } from 'react'
import { formatTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { audioControls, usePlayback } from '@/player/audio'

/** Progress bar with buffered range; drag previews, release seeks. */
export function SeekBar({ className, compact = false }: { className?: string; compact?: boolean }) {
  const currentTime = usePlayback((s) => s.currentTime)
  const duration = usePlayback((s) => s.duration)
  const bufferedEnd = usePlayback((s) => s.bufferedEnd)
  const [drag, setDrag] = useState<number | null>(null)

  const max = duration > 0 ? duration : 1
  const shown = drag ?? currentTime
  const bufferedPct = Math.min(100, (bufferedEnd / max) * 100)
  const disabled = duration <= 0

  return (
    <div className={cn('flex w-full items-center gap-2 text-[11px] text-muted-foreground tabular-nums', className)}>
      {compact ? null : <span className="w-10 text-right">{formatTime(shown)}</span>}
      <SliderPrimitive.Root
        className="group relative flex h-4 flex-1 touch-none items-center select-none data-[disabled]:opacity-50"
        min={0}
        max={max}
        step={0.5}
        value={[Math.min(shown, max)]}
        disabled={disabled}
        aria-label="Seek"
        onValueChange={([v]) => setDrag(v ?? 0)}
        onValueCommit={([v]) => {
          audioControls.seek(v ?? 0)
          setDrag(null)
        }}
      >
        <SliderPrimitive.Track className="relative h-1 grow overflow-hidden rounded-full bg-muted group-hover:h-1.5">
          <div
            data-testid="seek-buffered"
            className="absolute inset-y-0 left-0 rounded-full bg-foreground/15"
            style={{ width: `${bufferedPct}%` }}
          />
          <SliderPrimitive.Range className="absolute h-full rounded-full bg-foreground group-hover:bg-primary" />
        </SliderPrimitive.Track>
        <SliderPrimitive.Thumb
          aria-valuetext={`${formatTime(shown)} of ${formatTime(duration)}`}
          className="block size-3 rounded-full bg-foreground opacity-0 shadow transition-opacity group-hover:opacity-100 focus-visible:opacity-100 focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none"
        />
      </SliderPrimitive.Root>
      {compact ? null : <span className="w-10">{formatTime(duration)}</span>}
    </div>
  )
}
