import { useEffect, useMemo, useRef } from 'react'
import { toast } from 'sonner'
import { audioControls, registerAudioElement, safePlay, usePlayback } from './audio'
import { itemDuration, itemSrc } from './itemMeta'
import { useKeyboardShortcuts } from './keyboard'
import { type TrackEndReason, lifecycle } from './lifecycle'
import {
  installMediaSessionHandlers,
  setMediaSessionMetadata,
  setMediaSessionPlaybackState,
  setMediaSessionPosition,
} from './mediaSession'
import { usePlayer } from './playerStore'
import { type QueueItem, currentItem, hasNext, itemTitle, upcomingItem } from './queue'

type Session = { item: QueueItem; started: boolean; listened: number; lastTime: number }

function bufferedEndAt(el: HTMLAudioElement): number {
  const t = el.currentTime
  const ranges = el.buffered
  for (let i = 0; i < ranges.length; i++) {
    if (ranges.start(i) <= t + 0.5 && ranges.end(i) >= t) return ranges.end(i)
  }
  return 0
}

/**
 * Owns the single <audio> element. Mounted once, outside the router outlet, so
 * playback survives navigation. Renders nothing visible.
 */
export function AudioEngine() {
  const audioRef = useRef<HTMLAudioElement>(null)
  const session = useRef<Session | null>(null)
  const errorStreak = useRef(0)
  const lastPositionPush = useRef(0)

  const currentUid = usePlayer((s) => currentItem(s)?.uid)
  const restartToken = usePlayer((s) => s.restartToken)
  const upcoming = usePlayer((s) => upcomingItem(s))

  const endSession = (reason: TrackEndReason) => {
    const s = session.current
    if (!s) return
    session.current = null
    const el = audioRef.current
    const duration = el && Number.isFinite(el.duration) ? el.duration : (itemDuration(s.item) ?? 0)
    if (s.started) lifecycle.onTrackEnded(s.item, { reason, listened: s.listened, duration })
  }

  useEffect(() => {
    registerAudioElement(audioRef.current)
    const uninstall = installMediaSessionHandlers({
      play: audioControls.play,
      pause: audioControls.pause,
      next: () => usePlayer.getState().next(),
      prev: () => usePlayer.getState().prev(),
      seekTo: audioControls.seek,
      seekBy: audioControls.seekBy,
    })
    return () => {
      uninstall()
      registerAudioElement(null)
    }
  }, [])

  // Load the current queue entry whenever it changes.
  useEffect(() => {
    const el = audioRef.current
    if (!el) return
    endSession('skipped')
    const item = currentItem(usePlayer.getState())
    setMediaSessionMetadata(item)
    if (!item) {
      el.pause()
      el.removeAttribute('src')
      el.load()
      usePlayback.setState({ isPlaying: false, isLoading: false, currentTime: 0, duration: 0, bufferedEnd: 0 })
      return
    }
    session.current = { item, started: false, listened: 0, lastTime: 0 }
    el.src = itemSrc(item)
    usePlayback.setState({
      currentTime: 0,
      duration: itemDuration(item) ?? 0,
      bufferedEnd: 0,
      isLoading: usePlayback.getState().intent,
    })
    if (usePlayback.getState().intent) void safePlay()
  }, [currentUid])

  // Restart current track (prev >3s in, repeat-all on a single item, re-click current).
  const firstRestart = useRef(true)
  useEffect(() => {
    if (firstRestart.current) {
      firstRestart.current = false
      return
    }
    const el = audioRef.current
    if (!el || !el.getAttribute('src')) return
    el.currentTime = 0
    usePlayback.setState({ currentTime: 0 })
    if (usePlayback.getState().intent) void safePlay()
  }, [restartToken])

  // Warm the cache for the next track with a detached, never-played element.
  useEffect(() => {
    if (!upcoming || upcoming.uid === currentUid) return
    const pre = new Audio()
    pre.preload = 'auto'
    pre.muted = true
    pre.src = itemSrc(upcoming)
    return () => {
      pre.removeAttribute('src')
      pre.load()
    }
  }, [upcoming, currentUid])

  const shortcuts = useMemo(
    () => ({
      toggle: audioControls.toggle,
      seekBack: () => audioControls.seekBy(-10),
      seekForward: () => audioControls.seekBy(10),
      prev: () => usePlayer.getState().prev(),
      next: () => usePlayer.getState().next(),
    }),
    [],
  )
  useKeyboardShortcuts(shortcuts)

  const onPlaying = () => {
    errorStreak.current = 0
    usePlayback.setState({ isPlaying: true, isLoading: false, intent: true })
    setMediaSessionPlaybackState(true)
    const s = session.current
    if (s && !s.started) {
      s.started = true
      lifecycle.onTrackStarted(s.item)
    }
  }

  const onPause = () => {
    usePlayback.setState({ isPlaying: false })
    setMediaSessionPlaybackState(false)
  }

  const onTimeUpdate = () => {
    const el = audioRef.current
    if (!el) return
    const t = el.currentTime
    const duration = Number.isFinite(el.duration) ? el.duration : usePlayback.getState().duration
    usePlayback.setState({ currentTime: t, bufferedEnd: bufferedEndAt(el) })
    const s = session.current
    if (s && !el.paused) {
      const delta = t - s.lastTime
      if (delta > 0 && delta < 1.5) s.listened += delta
      s.lastTime = t
      lifecycle.onTrackProgress(s.item, t, duration)
    } else if (s) {
      s.lastTime = t
    }
    const now = performance.now()
    if (now - lastPositionPush.current > 1000) {
      lastPositionPush.current = now
      setMediaSessionPosition(t, duration)
    }
  }

  const onDuration = () => {
    const el = audioRef.current
    if (el && Number.isFinite(el.duration) && el.duration > 0) usePlayback.setState({ duration: el.duration })
  }

  const onEnded = () => {
    const el = audioRef.current
    const state = usePlayer.getState()
    endSession('ended')
    if (state.repeat === 'one' && el) {
      const item = currentItem(state)
      if (item) session.current = { item, started: false, listened: 0, lastTime: 0 }
      el.currentTime = 0
      void safePlay()
      return
    }
    if (hasNext(state)) {
      state.next()
      return
    }
    // end of queue — stop at the top of the last track
    usePlayback.setState({ intent: false, isPlaying: false, currentTime: 0 })
    if (el) el.currentTime = 0
  }

  const onError = () => {
    const el = audioRef.current
    if (!el || !el.getAttribute('src')) return
    const state = usePlayer.getState()
    const item = currentItem(state)
    endSession('error')
    errorStreak.current += 1
    usePlayback.setState({ isLoading: false, isPlaying: false })
    const title = item ? itemTitle(item) : 'this track'
    const canSkip = hasNext(state) && errorStreak.current < state.queue.length
    toast.error(`Couldn't play "${title}"`, {
      id: 'audio-error',
      description: canSkip ? 'Skipping to the next track.' : 'Playback stopped.',
    })
    if (canSkip) state.next()
    else {
      errorStreak.current = 0
      usePlayback.setState({ intent: false })
    }
  }

  return (
    <audio
      ref={audioRef}
      preload="auto"
      hidden
      data-testid="audio-engine"
      onPlaying={onPlaying}
      onPause={onPause}
      onWaiting={() => usePlayback.setState({ isLoading: true })}
      onCanPlay={() => usePlayback.setState({ isLoading: false })}
      onTimeUpdate={onTimeUpdate}
      onProgress={() => audioRef.current && usePlayback.setState({ bufferedEnd: bufferedEndAt(audioRef.current) })}
      onDurationChange={onDuration}
      onLoadedMetadata={onDuration}
      onEnded={onEnded}
      onError={onError}
    />
  )
}
