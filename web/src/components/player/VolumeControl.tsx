import { Volume1, Volume2, VolumeX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { audioControls, usePlayback } from '@/player/audio'

export function VolumeControl() {
  const volume = usePlayback((s) => s.volume)
  const muted = usePlayback((s) => s.muted)
  const effective = muted ? 0 : volume
  const Icon = effective === 0 ? VolumeX : effective < 0.5 ? Volume1 : Volume2
  return (
    <div className="flex w-36 items-center gap-1">
      <Button
        variant="ghost"
        size="icon"
        className="size-8 text-muted-foreground hover:text-foreground"
        onClick={audioControls.toggleMute}
        aria-label={muted ? 'Unmute' : 'Mute'}
      >
        <Icon />
      </Button>
      <Slider
        aria-label="Volume"
        min={0}
        max={1}
        step={0.01}
        value={[effective]}
        onValueChange={([v]) => audioControls.setVolume(v ?? 0)}
        className="flex-1"
      />
    </div>
  )
}
