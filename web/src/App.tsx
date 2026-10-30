import { QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { Toaster } from 'sonner'
import { makeQueryClient } from '@/api/queryClient'
import { AppShell, RoutedMain } from '@/components/layout/AppShell'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useUi } from '@/lib/uiStore'
import { AudioEngine } from '@/player/AudioEngine'
import { PlayerSync } from '@/player/PlayerSync'
import { NewPlaylistDialog } from '@/playlists/NewPlaylistDialog'
import { ArchiveIndexView, ArchivePlaylistView } from '@/views/ArchiveViews'
import { AlbumView } from '@/views/AlbumView'
import { DiscoverView } from '@/views/DiscoverView'
import { ArtistView } from '@/views/ArtistView'
import { HomeView } from '@/views/HomeView'
import { LibraryView } from '@/views/LibraryView'
import { LikedView, PlaylistView, PlaylistsView } from '@/views/PlaylistViews'
import { NotFoundView } from '@/views/MiscViews'
import { QueueView } from '@/views/QueueView'
import { SearchView } from '@/views/SearchView'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<RoutedMain />}>
        <Route index element={<HomeView />} />
        <Route path="search" element={<SearchView />} />
        <Route path="library" element={<LibraryView />} />
        <Route path="discover" element={<DiscoverView />} />
        <Route path="artist/:id" element={<ArtistView />} />
        <Route path="album/:id" element={<AlbumView />} />
        <Route path="queue" element={<QueueView />} />
        <Route path="playlists" element={<PlaylistsView />} />
        <Route path="playlist/:id" element={<PlaylistView />} />
        <Route path="liked" element={<LikedView />} />
        <Route path="archive" element={<ArchiveIndexView />} />
        <Route path="archive/:id" element={<ArchivePlaylistView />} />
        <Route path="*" element={<NotFoundView />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  const [queryClient] = useState(makeQueryClient)
  const theme = useUi((s) => s.theme)
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={400}>
        <BrowserRouter>
          {/* PlayerBar + AudioEngine sit outside <Routes>, so navigation never unmounts playback. */}
          <AppShell>
            <AppRoutes />
          </AppShell>
          <AudioEngine />
          <PlayerSync />
          <NewPlaylistDialog />
        </BrowserRouter>
        <Toaster theme={theme} position="bottom-center" offset={96} richColors closeButton />
      </TooltipProvider>
    </QueryClientProvider>
  )
}
