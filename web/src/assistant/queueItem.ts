import type { ChatTrack } from '@/api/types'
import type { QueueItemInput } from '@/player/queue'

/** Queue entry for a chat track: the library song, else its 30s preview; null = YouTube only. */
export function queueItemFor(track: ChatTrack): QueueItemInput | null {
  const p = track.playable
  if (p.song) return { kind: 'library', song: p.song }
  if (p.previewUrl) {
    return { kind: 'preview', url: p.previewUrl, artist: track.artist, title: track.title, coverUrl: p.coverUrl }
  }
  return null
}
