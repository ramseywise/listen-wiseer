import { toast } from 'sonner'
import { isLibraryOffline } from '@/api/client'
import { type RadioSeed, radio } from './radio'

/** UI entry point: start radio around `seed` with toasts for the slow / empty / failed cases. */
export async function startRadio(seed: RadioSeed, label: string): Promise<void> {
  const id = toast.loading('Starting radio…', { description: label })
  try {
    const ok = await radio.start(seed)
    if (ok) toast.success('Radio on', { id, description: `Tracks like ${label}` })
    else toast.error('No similar tracks found', { id, description: label })
  } catch (err) {
    toast.error(isLibraryOffline(err) ? 'Library is offline' : "Couldn't start radio", { id })
  }
}
