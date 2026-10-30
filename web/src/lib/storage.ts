// localStorage wrappers that never throw (private mode, quota, disabled storage).
// Per D4, localStorage is for UI prefs only (panel open, volume, theme) — the queue
// itself is persisted server-side via savePlayQueue in P3.

const PREFIX = 'lw:'

export function readPref<T>(key: string, fallback: T, validate?: (v: unknown) => v is T): T {
  try {
    const raw = window.localStorage.getItem(PREFIX + key)
    if (raw === null) return fallback
    const parsed: unknown = JSON.parse(raw)
    if (validate) return validate(parsed) ? parsed : fallback
    return parsed as T
  } catch {
    return fallback
  }
}

export function writePref(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    // storage unavailable — prefs just won't persist
  }
}

export const isBoolean = (v: unknown): v is boolean => typeof v === 'boolean'
export const isNumber = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
