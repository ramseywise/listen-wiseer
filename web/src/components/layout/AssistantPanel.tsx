import { Sparkles, SquarePen, X } from 'lucide-react'
import { AssistantChat } from '@/assistant/AssistantChat'
import { useChat } from '@/assistant/chatStore'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { WIDE_QUERY } from '@/hooks/useToggleAssistant'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { useUi } from '@/lib/uiStore'


function AssistantBody({ onClose }: { onClose: () => void }) {
  const newChat = useChat((s) => s.newChat)
  const hasMessages = useChat((s) => s.messages.length > 0)
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Sparkles className="size-4 text-violet" /> Assistant
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" className="size-8" onClick={newChat} disabled={!hasMessages} aria-label="New chat">
            <SquarePen />
          </Button>
          <Button variant="ghost" size="icon" className="size-8" onClick={onClose} aria-label="Close assistant">
            <X />
          </Button>
        </div>
      </div>
      <AssistantChat />
    </div>
  )
}

/** Inline column on wide screens, a sheet on narrow ones. */
export function AssistantPanel() {
  const wide = useMediaQuery(WIDE_QUERY)
  const open = useUi((s) => s.assistantOpen)
  const setOpen = useUi((s) => s.setAssistantOpen)
  const sheetOpen = useUi((s) => s.assistantSheetOpen)
  const setSheetOpen = useUi((s) => s.setAssistantSheetOpen)

  if (wide) {
    if (!open) return null
    return (
      <aside aria-label="Assistant" className="w-[340px] shrink-0 border-l bg-surface">
        <AssistantBody onClose={() => setOpen(false)} />
      </aside>
    )
  }
  return (
    <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
      <SheetContent side="right" showCloseButton={false} className="w-[min(380px,100vw)] gap-0 bg-surface p-0">
        <SheetTitle className="sr-only">Assistant</SheetTitle>
        <SheetDescription className="sr-only">Music assistant chat</SheetDescription>
        <AssistantBody onClose={() => setSheetOpen(false)} />
      </SheetContent>
    </Sheet>
  )
}
