import { create } from 'zustand'
import { isBoolean, readPref, writePref } from './storage'

export type Theme = 'dark' | 'light'

type UiState = {
  /** Inline assistant panel on wide screens — persisted. */
  assistantOpen: boolean
  /** Assistant sheet on narrow screens — not persisted (don't pop a sheet on load). */
  assistantSheetOpen: boolean
  queueOpen: boolean
  theme: Theme
  setAssistantOpen: (open: boolean) => void
  setAssistantSheetOpen: (open: boolean) => void
  setQueueOpen: (open: boolean) => void
  toggleTheme: () => void
}

const isTheme = (v: unknown): v is Theme => v === 'dark' || v === 'light'

export function applyTheme(theme: Theme): void {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.classList.toggle('light', theme === 'light')
}

export const useUi = create<UiState>((set, get) => ({
  assistantOpen: readPref('assistantOpen', false, isBoolean),
  assistantSheetOpen: false,
  queueOpen: false,
  theme: readPref('theme', 'dark', isTheme),
  setAssistantOpen: (assistantOpen) => {
    writePref('assistantOpen', assistantOpen)
    set({ assistantOpen })
  },
  setAssistantSheetOpen: (assistantSheetOpen) => set({ assistantSheetOpen }),
  setQueueOpen: (queueOpen) => set({ queueOpen }),
  toggleTheme: () => {
    const theme: Theme = get().theme === 'dark' ? 'light' : 'dark'
    writePref('theme', theme)
    applyTheme(theme)
    set({ theme })
  },
}))
