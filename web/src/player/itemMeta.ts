import { coverUrl, streamUrl } from '@/api/client'
import type { QueueItem } from './queue'

export function itemSrc(item: QueueItem): string {
  return item.kind === 'library' ? streamUrl(item.song.id) : item.url
}

export function itemCover(item: QueueItem, size = 300): string | undefined {
  return item.kind === 'library' ? coverUrl(item.song.coverArt, size) : item.coverUrl
}

export function itemAlbum(item: QueueItem): string | undefined {
  return item.kind === 'library' ? item.song.album : undefined
}

export function itemDuration(item: QueueItem): number | undefined {
  return item.kind === 'library' ? item.song.duration : undefined
}
