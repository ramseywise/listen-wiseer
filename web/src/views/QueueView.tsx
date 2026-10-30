import { QueueList } from '@/components/player/QueueList'

export function QueueView() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <h1 className="pt-2 text-2xl font-bold tracking-tight md:text-3xl">Queue</h1>
      <QueueList />
    </div>
  )
}
