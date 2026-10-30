import { create } from 'zustand'
import { isBoolean, isNumber, readPref, writePref } from '@/lib/storage'

// Imperative handle on the single <audio> element (registered by <AudioEngine>) plus a
// small store of transient playback state for the UI.

export type PlaybackState = {
  /** What the user wants: true after play / playNow, false after pause. */
  intent: boolean
  /** What the element is actually doing. */
  isPlaying: boolean
  isLoading: boolean
  currentTime: number
  duration: number
  /** End (seconds) of the buffered range around currentTime. */
  bufferedEnd: number
  volume: number
  muted: boolean
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, v))

export const usePlayback = create<PlaybackState>(() => ({
  intent: false,
  isPlaying: false,
  isLoading: false,
  currentTime: 0,
  duration: 0,
  bufferedEnd: 0,
  volume: clamp01(readPref('volume', 0.8, isNumber)),
  muted: readPref('muted', false, isBoolean),
}))

let el: HTMLAudioElement | null = null

export function registerAudioElement(node: HTMLAudioElement | null): void {
  el = node
  if (el) {
    const { volume, muted } = usePlayback.getState()
    el.volume = volume
    el.muted = muted
  }
}

export function getAudioElement(): HTMLAudioElement | null {
  return el
}

/** Start the element; swallows the AbortError raised when src changes mid-play. */
export async function safePlay(): Promise<void> {
  if (!el || !el.src) return
  try {
    await el.play()
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') return
    if (err instanceof DOMException && err.name === 'NotAllowedError') {
      // autoplay policy — needs a user gesture; leave intent so the next click works
      usePlayback.setState({ isPlaying: false })
      return
    }
    // NotSupportedError etc. surface through the element's `error` event
  }
}

export const audioControls = {
  play(): void {
    usePlayback.setState({ intent: true })
    void safePlay()
  },
  pause(): void {
    usePlayback.setState({ intent: false })
    el?.pause()
  },
  toggle(): void {
    if (usePlayback.getState().intent && el && !el.paused) audioControls.pause()
    else audioControls.play()
  },
  seek(seconds: number): void {
    if (!el) return
    const max = Number.isFinite(el.duration) ? el.duration : Infinity
    const t = Math.max(0, Math.min(seconds, max))
    el.currentTime = t
    usePlayback.setState({ currentTime: t })
  },
  seekBy(delta: number): void {
    audioControls.seek(audioControls.currentTime() + delta)
  },
  currentTime(): number {
    return el?.currentTime ?? usePlayback.getState().currentTime
  },
  setVolume(v: number): void {
    const volume = clamp01(v)
    if (el) {
      el.volume = volume
      if (volume > 0 && el.muted) el.muted = false
    }
    const muted = volume > 0 ? false : usePlayback.getState().muted
    usePlayback.setState({ volume, muted })
    writePref('volume', volume)
    writePref('muted', muted)
  },
  toggleMute(): void {
    const muted = !usePlayback.getState().muted
    if (el) el.muted = muted
    usePlayback.setState({ muted })
    writePref('muted', muted)
  },
}
