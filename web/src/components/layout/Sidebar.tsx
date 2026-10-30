import { Menu, Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { NavLink } from 'react-router'
import { useHealth } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useUi } from '@/lib/uiStore'
import { cn } from '@/lib/utils'
import { Logo } from './Logo'
import { type NavItem, collectionNav, primaryNav } from './nav'
import { SidebarArchive, SidebarPlaylists } from './SidebarCollections'

function NavRow({ item, expanded = false }: { item: NavItem; expanded?: boolean }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground',
          isActive && 'bg-accent text-foreground',
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon className={cn('size-[18px] shrink-0', isActive && 'text-primary')} />
          <span className={cn('truncate', !expanded && 'max-lg:sr-only')}>{item.label}</span>
          {item.soon ? (
            <span
              className={cn(
                'ml-auto rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase',
                !expanded && 'max-lg:hidden',
              )}
            >
              soon
            </span>
          ) : null}
        </>
      )}
    </NavLink>
  )
}

function LibraryStatus() {
  const { data, isError } = useHealth()
  const online = data?.navidrome === true && !isError
  const label = data === undefined && !isError ? 'Connecting…' : online ? `${data.songCount} songs` : 'Library offline'
  return (
    <div className="flex items-center gap-2 px-3 text-xs text-muted-foreground max-lg:justify-center" title={label}>
      <span
        className={cn(
          'size-2 shrink-0 rounded-full',
          data === undefined && !isError ? 'bg-muted-foreground/50' : online ? 'bg-primary' : 'bg-destructive',
        )}
      />
      <span className="truncate max-lg:sr-only">{label}</span>
    </div>
  )
}

export function Sidebar() {
  const theme = useUi((s) => s.theme)
  const toggleTheme = useUi((s) => s.toggleTheme)
  return (
    <nav
      aria-label="Main"
      className="hidden w-[76px] shrink-0 flex-col gap-6 border-r bg-surface px-3 py-5 md:flex lg:w-60"
    >
      <div className="px-1 max-lg:flex max-lg:justify-center">
        <span className="max-lg:hidden">
          <Logo />
        </span>
        <span className="lg:hidden">
          <Logo compact />
        </span>
      </div>
      <div className="flex flex-col gap-1">
        {primaryNav.map((item) => (
          <NavRow key={item.to} item={item} />
        ))}
      </div>
      <div className="flex flex-col gap-1">
        <div className="px-3 text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase max-lg:sr-only">
          Your music
        </div>
        {collectionNav.map((item) => (
          <NavRow key={item.to} item={item} />
        ))}
      </div>
      <div className="scrollbar-thin -mx-1 hidden min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-1 lg:flex">
        <SidebarPlaylists />
        <SidebarArchive />
      </div>
      <div className="mt-auto flex flex-col gap-3">
        <LibraryStatus />
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleTheme}
          className="justify-start gap-3 px-3 text-muted-foreground max-lg:justify-center"
          aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
        >
          {theme === 'dark' ? <Sun /> : <Moon />}
          <span className="max-lg:sr-only">{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
        </Button>
      </div>
    </nav>
  )
}

const mobileTab = (isActive: boolean) =>
  cn('flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] text-muted-foreground', isActive && 'text-primary')

/** Small screens: the primary tabs + "More" — a sheet with playlists, likes and the archive. */
export function MobileNav() {
  const [moreOpen, setMoreOpen] = useState(false)
  return (
    <nav aria-label="Main" className="flex border-t bg-surface md:hidden">
      {primaryNav.map((item) => {
        const Icon = item.icon
        return (
          <NavLink key={item.to} to={item.to} end={item.to === '/'} className={({ isActive }) => mobileTab(isActive)}>
            <Icon className="size-5" />
            {item.label}
          </NavLink>
        )
      })}
      <button type="button" className={mobileTab(moreOpen)} onClick={() => setMoreOpen(true)} aria-haspopup="dialog">
        <Menu className="size-5" />
        More
      </button>
      <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
        <SheetContent side="bottom" className="max-h-[80dvh] gap-0 rounded-t-xl">
          <SheetHeader>
            <SheetTitle>Your music</SheetTitle>
            <SheetDescription className="sr-only">Playlists, liked songs and the archive</SheetDescription>
          </SheetHeader>
          {/* any link inside closes the sheet */}
          <div
            className="scrollbar-thin flex min-h-0 flex-col gap-4 overflow-y-auto px-3 pb-6"
            onClick={(e) => {
              if ((e.target as HTMLElement).closest('a')) setMoreOpen(false)
            }}
          >
            <div className="flex flex-col gap-1">
              {collectionNav.map((item) => (
                <NavRow key={item.to} item={item} expanded />
              ))}
            </div>
            <SidebarPlaylists />
            <SidebarArchive />
          </div>
        </SheetContent>
      </Sheet>
    </nav>
  )
}
