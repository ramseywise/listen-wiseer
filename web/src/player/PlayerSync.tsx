import { useEffect } from 'react'
import { api } from '@/api/client'
import { audioControls, getAudioElement, usePlayback } from './audio'
import { setLifecycleHooks } from './lifecycle'
import { usePlayer } from './playerStore'
import { createTracker, restoredQueue } from './tracking'

/** Seek the (paused) element once the restored track's metadata is in. */
function seekWhenReady(position: number): void {
  const el = getAudioElement()
  if (!el || position <= 0) return
  el.addEventListener(
    'loadedmetadata',
    () => {
      el.currentTime = position
      usePlayback.setState({ currentTime: position })
    },
    { once: true },
  )
}

/**
 * Wires play tracking + queue persistence into the player lifecycle, and on load restores
 * the saved queue paused at the saved position. Renders nothing.
 */
export function PlayerSync() {
  useEffect(() => {
    const tracker = createTracker({
      scrobble: api.scrobble,
      saveQueue: api.saveQueue,
      getQueue: () => usePlayer.getState(),
      currentTime: () => audioControls.currentTime(),
    })
    const unregister = setLifecycleHooks(tracker.hooks)
    let active = true
    const controller = new AbortController()
    api
      .savedQueue(controller.signal)
      .then((saved) => {
        const player = usePlayer.getState()
        // the user already started something — don't clobber it
        if (!active || player.queue.length > 0) return
        const restored = restoredQueue(saved, player.shuffle)
        if (!restored) return
        usePlayback.setState({ intent: false })
        tracker.quietly(() => usePlayer.setState(restored))
        if (saved.songs.some((s) => s.id === saved.current)) seekWhenReady(saved.position)
      })
      .catch(() => {}) // offline / nothing saved — start empty
    const onHide = () => tracker.flushOnUnload()
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') tracker.flushOnUnload()
    }
    window.addEventListener('pagehide', onHide)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      active = false
      controller.abort()
      window.removeEventListener('pagehide', onHide)
      document.removeEventListener('visibilitychange', onVisibility)
      unregister()
      tracker.dispose()
    }
  }, [])
  return null
}
