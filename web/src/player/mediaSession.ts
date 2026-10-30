import { itemAlbum, itemCover } from './itemMeta'
import { type QueueItem, itemArtist, itemTitle } from './queue'

// OS media keys / lock screen / headset buttons.

function supported(): boolean {
  return typeof navigator !== 'undefined' && 'mediaSession' in navigator
}

export type MediaSessionCallbacks = {
  play: () => void
  pause: () => void
  next: () => void
  prev: () => void
  seekTo: (t: number) => void
  seekBy: (delta: number) => void
}

export function installMediaSessionHandlers(cb: MediaSessionCallbacks): () => void {
  if (!supported()) return () => {}
  const ms = navigator.mediaSession
  const handlers: [MediaSessionAction, MediaSessionActionHandler][] = [
    ['play', () => cb.play()],
    ['pause', () => cb.pause()],
    ['nexttrack', () => cb.next()],
    ['previoustrack', () => cb.prev()],
    ['seekto', (d) => d.seekTime !== undefined && cb.seekTo(d.seekTime)],
    ['seekbackward', (d) => cb.seekBy(-(d.seekOffset ?? 10))],
    ['seekforward', (d) => cb.seekBy(d.seekOffset ?? 10)],
  ]
  for (const [action, handler] of handlers) {
    try {
      ms.setActionHandler(action, handler)
    } catch {
      // action not supported by this browser
    }
  }
  return () => {
    for (const [action] of handlers) {
      try {
        ms.setActionHandler(action, null)
      } catch {
        // ignore
      }
    }
  }
}

export function setMediaSessionMetadata(item: QueueItem | undefined): void {
  if (!supported() || typeof MediaMetadata === 'undefined') return
  if (!item) {
    navigator.mediaSession.metadata = null
    return
  }
  const artwork = [96, 256, 512]
    .map((size) => ({ src: itemCover(item, size), size }))
    .filter((a): a is { src: string; size: number } => a.src !== undefined)
    .map(({ src, size }) => ({ src: new URL(src, window.location.href).href, sizes: `${size}x${size}` }))
  navigator.mediaSession.metadata = new MediaMetadata({
    title: itemTitle(item),
    artist: itemArtist(item),
    album: itemAlbum(item) ?? '',
    artwork,
  })
}

export function setMediaSessionPlaybackState(playing: boolean): void {
  if (!supported()) return
  navigator.mediaSession.playbackState = playing ? 'playing' : 'paused'
}

export function setMediaSessionPosition(position: number, duration: number): void {
  if (!supported() || !('setPositionState' in navigator.mediaSession)) return
  if (!Number.isFinite(duration) || duration <= 0) return
  try {
    navigator.mediaSession.setPositionState({
      duration,
      position: Math.min(position, duration),
      playbackRate: 1,
    })
  } catch {
    // invalid state during source switch
  }
}
