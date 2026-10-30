import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { AudioLines, GripVertical, ListMusic, Radio, X } from 'lucide-react'
import { useMemo } from 'react'
import { CoverArt } from '@/components/music/CoverArt'
import { EmptyState } from '@/components/states/States'
import { Button } from '@/components/ui/button'
import { formatTime, formatTotal, plural } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePlayback } from '@/player/audio'
import { itemCover, itemDuration } from '@/player/itemMeta'
import { usePlayer } from '@/player/playerStore'
import { type QueueItem, currentItem, itemArtist, itemTitle, upNext } from '@/player/queue'

function QueueRow({
  item,
  onPlay,
  onRemove,
  sortable = true,
  playing = false,
}: {
  item: QueueItem
  onPlay?: () => void
  onRemove?: () => void
  sortable?: boolean
  playing?: boolean
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: item.uid,
    disabled: !sortable,
  })
  const duration = itemDuration(item)
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-testid="queue-row"
      className={cn(
        'group flex h-14 items-center gap-2 rounded-md pr-1 pl-1 hover:bg-accent/60',
        isDragging && 'relative z-10 bg-accent shadow-lg',
      )}
      onDoubleClick={onPlay}
    >
      {sortable ? (
        <button
          ref={setActivatorNodeRef}
          type="button"
          aria-label={`Reorder ${itemTitle(item)}`}
          className="flex h-full w-6 cursor-grab touch-none items-center justify-center text-muted-foreground/60 hover:text-foreground active:cursor-grabbing"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="size-4" />
        </button>
      ) : (
        <div className="flex w-6 justify-center text-primary">
          <AudioLines className={cn('size-4', playing && 'animate-pulse')} />
        </div>
      )}
      <button type="button" onClick={onPlay} className="flex min-w-0 flex-1 items-center gap-3 text-left" aria-label={`Play ${itemTitle(item)}`}>
        <CoverArt src={itemCover(item, 80)} alt="" className="size-10 rounded" />
        <span className="min-w-0">
          <span className={cn('block truncate text-sm font-medium', !sortable && 'text-primary')}>{itemTitle(item)}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {item.radio ? (
              <span className="mr-1.5 inline-flex items-center gap-0.5 rounded-sm bg-primary/15 px-1 text-[10px] font-medium text-primary uppercase">
                <Radio className="size-2.5" aria-hidden />
                radio
              </span>
            ) : null}
            {itemArtist(item)}
            {item.kind === 'preview' ? ' · preview' : ''}
          </span>
        </span>
      </button>
      {duration !== undefined ? (
        <span className="text-xs text-muted-foreground tabular-nums">{formatTime(duration)}</span>
      ) : null}
      {onRemove ? (
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
          aria-label={`Remove ${itemTitle(item)} from queue`}
          onClick={onRemove}
        >
          <X />
        </Button>
      ) : null}
    </li>
  )
}

export function QueueList() {
  const queue = usePlayer((s) => s.queue)
  const index = usePlayer((s) => s.index)
  const current = usePlayer((s) => currentItem(s))
  const upcoming = useMemo(() => upNext({ queue, index }), [queue, index])
  const { move, remove, jumpTo, clear } = usePlayer.getState()
  const isPlaying = usePlayback((s) => s.isPlaying)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return
    const from = queue.findIndex((q) => q.uid === active.id)
    const to = queue.findIndex((q) => q.uid === over.id)
    if (from >= 0 && to >= 0) move(from, to)
  }

  if (!current) {
    return (
      <EmptyState icon={<ListMusic />} title="Your queue is empty">
        Play an album or use “Add to queue” on any track to line things up here.
      </EmptyState>
    )
  }

  const remaining = upcoming.reduce((s, i) => s + (itemDuration(i) ?? 0), 0)

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h3 className="mb-1 px-1 text-xs font-semibold tracking-wider text-muted-foreground uppercase">Now playing</h3>
        <ul>
          <QueueRow item={current} sortable={false} playing={isPlaying} />
        </ul>
      </section>
      <section>
        <div className="mb-1 flex items-baseline justify-between px-1">
          <h3 className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">Up next</h3>
          {upcoming.length > 0 ? (
            <span className="text-xs text-muted-foreground">
              {plural(upcoming.length, 'track')}
              {remaining > 0 ? ` · ${formatTotal(remaining)}` : ''}
            </span>
          ) : null}
        </div>
        {upcoming.length === 0 ? (
          <p className="px-1 py-3 text-sm text-muted-foreground">Nothing queued after this track.</p>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd} modifiers={[restrictToVerticalAxis]}>
            <SortableContext items={upcoming.map((i) => i.uid)} strategy={verticalListSortingStrategy}>
              <ul aria-label="Up next">
                {upcoming.map((item, i) => (
                  <QueueRow
                    key={item.uid}
                    item={item}
                    onPlay={() => jumpTo(index + 1 + i)}
                    onRemove={() => remove(item.uid)}
                  />
                ))}
              </ul>
            </SortableContext>
          </DndContext>
        )}
      </section>
      {queue.length > 1 ? (
        <div className="px-1">
          <Button variant="outline" size="sm" onClick={clear}>
            Clear queue
          </Button>
        </div>
      ) : null}
    </div>
  )
}
