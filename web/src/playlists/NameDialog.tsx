import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  initial?: string
  submitLabel: string
  pending?: boolean
  onSubmit: (name: string) => void
}

/** Single-field name prompt (new playlist / rename). */
export function NameDialog({ open, onOpenChange, title, description, initial = '', submitLabel, pending, onSubmit }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* keyed so the field resets to `initial` each time it opens */}
        {open ? (
          <NameForm
            key={initial}
            title={title}
            description={description}
            initial={initial}
            submitLabel={submitLabel}
            pending={pending}
            onSubmit={onSubmit}
            onCancel={() => onOpenChange(false)}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function NameForm({
  title,
  description,
  initial,
  submitLabel,
  pending,
  onSubmit,
  onCancel,
}: Omit<Props, 'open' | 'onOpenChange'> & { initial: string; onCancel: () => void }) {
  const [name, setName] = useState(initial)
  const trimmed = name.trim()
  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (trimmed) onSubmit(trimmed)
      }}
    >
      <div className="grid gap-1.5">
        <DialogTitle>{title}</DialogTitle>
        {description ? <DialogDescription>{description}</DialogDescription> : <DialogDescription className="sr-only">{title}</DialogDescription>}
      </div>
      <input
        aria-label="Playlist name"
        autoFocus
        value={name}
        maxLength={200}
        onChange={(e) => setName(e.target.value)}
        placeholder="My playlist"
        className="h-10 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={!trimmed || pending}>
          {submitLabel}
        </Button>
      </div>
    </form>
  )
}
