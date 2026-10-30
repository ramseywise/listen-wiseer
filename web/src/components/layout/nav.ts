import { Archive, Compass, Heart, Home, Library, ListMusic, type LucideIcon, Search } from 'lucide-react'

export type NavItem = { to: string; label: string; icon: LucideIcon; soon?: boolean }

export const primaryNav: NavItem[] = [
  { to: '/', label: 'Home', icon: Home },
  { to: '/search', label: 'Search', icon: Search },
  { to: '/library', label: 'Library', icon: Library },
  { to: '/discover', label: 'Discover', icon: Compass },
]

// Playlists + likes live in Navidrome; the archive is the read-only Spotify-era playlists.
export const collectionNav: NavItem[] = [
  { to: '/playlists', label: 'Playlists', icon: ListMusic },
  { to: '/liked', label: 'Liked Songs', icon: Heart },
  { to: '/archive', label: 'Archive', icon: Archive },
]
