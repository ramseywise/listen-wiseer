import { useUi } from '@/lib/uiStore'
import { useMediaQuery } from './useMediaQuery'

/** Breakpoint at which the assistant is an inline column rather than a sheet. */
export const WIDE_QUERY = '(min-width: 1280px)'

export function useToggleAssistant() {
  const wide = useMediaQuery(WIDE_QUERY)
  const open = useUi((s) => (wide ? s.assistantOpen : s.assistantSheetOpen))
  const setOpen = useUi((s) => s.setAssistantOpen)
  const setSheetOpen = useUi((s) => s.setAssistantSheetOpen)
  return { open, toggle: () => (wide ? setOpen(!open) : setSheetOpen(!open)) }
}
