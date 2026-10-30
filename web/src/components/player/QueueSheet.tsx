import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useUi } from '@/lib/uiStore'
import { QueueList } from './QueueList'

export function QueueSheet() {
  const open = useUi((s) => s.queueOpen)
  const setOpen = useUi((s) => s.setQueueOpen)
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent side="right" className="w-[min(420px,100vw)] gap-0 bg-surface sm:max-w-[420px]">
        <SheetHeader className="border-b">
          <SheetTitle>Queue</SheetTitle>
          <SheetDescription className="sr-only">Now playing and up next. Drag to reorder.</SheetDescription>
        </SheetHeader>
        <div className="scrollbar-thin flex-1 overflow-y-auto p-3">
          <QueueList />
        </div>
      </SheetContent>
    </Sheet>
  )
}
