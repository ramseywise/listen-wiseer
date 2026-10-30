import { useEffect, useRef } from 'react'
import { Outlet, useLocation } from 'react-router'
import { PlayerBar } from '@/components/player/PlayerBar'
import { QueueSheet } from '@/components/player/QueueSheet'
import { AssistantPanel } from './AssistantPanel'
import { MobileNav, Sidebar } from './Sidebar'

/** Routed content only. Player, queue and assistant live outside this in <App>. */
export function RoutedMain() {
  const ref = useRef<HTMLElement>(null)
  const { pathname } = useLocation()
  useEffect(() => {
    ref.current?.scrollTo({ top: 0 })
  }, [pathname])
  return (
    <main ref={ref} className="scrollbar-thin min-w-0 flex-1 overflow-y-auto px-4 py-4 md:px-8 md:py-6">
      <Outlet />
    </main>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        {children}
        <AssistantPanel />
      </div>
      <PlayerBar />
      <MobileNav />
      <QueueSheet />
    </div>
  )
}
