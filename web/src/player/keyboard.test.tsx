import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { isTypingTarget, shortcutFor, useKeyboardShortcuts } from './keyboard'

const key = (k: Partial<KeyboardEvent>) => ({
  key: '',
  code: '',
  shiftKey: false,
  metaKey: false,
  ctrlKey: false,
  altKey: false,
  ...k,
})

describe('shortcutFor', () => {
  it('maps the documented keys', () => {
    expect(shortcutFor(key({ key: ' ', code: 'Space' }))).toBe('toggle')
    expect(shortcutFor(key({ key: 'ArrowLeft' }))).toBe('seekBack')
    expect(shortcutFor(key({ key: 'ArrowRight' }))).toBe('seekForward')
    expect(shortcutFor(key({ key: 'ArrowLeft', shiftKey: true }))).toBe('prev')
    expect(shortcutFor(key({ key: 'ArrowRight', shiftKey: true }))).toBe('next')
  })

  it('ignores modified and unrelated keys', () => {
    expect(shortcutFor(key({ key: 'ArrowLeft', metaKey: true }))).toBeNull()
    expect(shortcutFor(key({ key: ' ', code: 'Space', ctrlKey: true }))).toBeNull()
    expect(shortcutFor(key({ key: 'a' }))).toBeNull()
  })
})

describe('isTypingTarget', () => {
  it('detects text inputs, textareas and contenteditable', () => {
    const text = document.createElement('input')
    const range = document.createElement('input')
    range.type = 'range'
    const area = document.createElement('textarea')
    const editable = document.createElement('div')
    editable.contentEditable = 'true'
    Object.defineProperty(editable, 'isContentEditable', { value: true })
    expect(isTypingTarget(text)).toBe(true)
    expect(isTypingTarget(area)).toBe(true)
    expect(isTypingTarget(editable)).toBe(true)
    expect(isTypingTarget(range)).toBe(false)
    expect(isTypingTarget(document.createElement('button'))).toBe(false)
    expect(isTypingTarget(null)).toBe(false)
  })
})

function Harness({ handlers }: { handlers: Parameters<typeof useKeyboardShortcuts>[0] }) {
  useKeyboardShortcuts(handlers)
  return (
    <div>
      <input aria-label="search" />
      <button type="button">btn</button>
    </div>
  )
}

describe('useKeyboardShortcuts', () => {
  const make = () => ({
    toggle: vi.fn(),
    seekBack: vi.fn(),
    seekForward: vi.fn(),
    prev: vi.fn(),
    next: vi.fn(),
  })

  it('dispatches on window keydown', () => {
    const h = make()
    render(<Harness handlers={h} />)
    fireEvent.keyDown(window, { key: ' ', code: 'Space' })
    fireEvent.keyDown(window, { key: 'ArrowRight', shiftKey: true })
    expect(h.toggle).toHaveBeenCalledOnce()
    expect(h.next).toHaveBeenCalledOnce()
  })

  it('is ignored while typing in an input', () => {
    const h = make()
    const { getByLabelText } = render(<Harness handlers={h} />)
    fireEvent.keyDown(getByLabelText('search'), { key: ' ', code: 'Space' })
    fireEvent.keyDown(getByLabelText('search'), { key: 'ArrowLeft' })
    expect(h.toggle).not.toHaveBeenCalled()
    expect(h.seekBack).not.toHaveBeenCalled()
  })

  it('works when a button has focus', () => {
    const h = make()
    const { getByText } = render(<Harness handlers={h} />)
    fireEvent.keyDown(getByText('btn'), { key: 'ArrowLeft' })
    expect(h.seekBack).toHaveBeenCalledOnce()
  })
})
