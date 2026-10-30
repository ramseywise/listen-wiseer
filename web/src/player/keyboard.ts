import { useEffect } from 'react'

export type ShortcutAction = 'toggle' | 'seekBack' | 'seekForward' | 'prev' | 'next'

/** True when the event comes from somewhere the user is typing. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (tag === 'INPUT') {
    const type = (target as HTMLInputElement).type
    return !['button', 'checkbox', 'radio', 'range', 'submit', 'reset'].includes(type)
  }
  return target.closest('[contenteditable="true"], [role="textbox"], [role="combobox"]') !== null
}

/** Pure key → action mapping (space, ←/→ seek ±10s, shift+←/→ prev/next). */
export function shortcutFor(e: Pick<KeyboardEvent, 'key' | 'code' | 'shiftKey' | 'metaKey' | 'ctrlKey' | 'altKey'>): ShortcutAction | null {
  if (e.metaKey || e.ctrlKey || e.altKey) return null
  if (e.code === 'Space' || e.key === ' ') return e.shiftKey ? null : 'toggle'
  if (e.key === 'ArrowLeft') return e.shiftKey ? 'prev' : 'seekBack'
  if (e.key === 'ArrowRight') return e.shiftKey ? 'next' : 'seekForward'
  return null
}

/** Sliders own their arrow keys; don't steal them. */
function isArrowOwner(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.closest('[role="slider"], [role="menu"], [role="listbox"]') !== null
}

export function useKeyboardShortcuts(handlers: Record<ShortcutAction, () => void>): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || isTypingTarget(e.target)) return
      const action = shortcutFor(e)
      if (!action) return
      if (e.repeat && action !== 'seekBack' && action !== 'seekForward') return
      if (action !== 'toggle' && isArrowOwner(e.target)) return
      e.preventDefault()
      handlers[action]()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [handlers])
}
