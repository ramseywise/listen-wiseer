import type { Album, AlbumSummary, Artist, ArtistSummary, Song } from '@/api/types'

// Small fictional library for mock mode and tests. Names are invented.

type AlbumSeed = {
  id: string
  name: string
  year: number
  tracks: [title: string, duration: number][]
}

type ArtistSeed = { id: string; name: string; albums: AlbumSeed[] }

const seeds: ArtistSeed[] = [
  {
    id: 'ar-1',
    name: 'Halcyon Drift',
    albums: [
      {
        id: 'al-1',
        name: 'Low Tide Signals',
        year: 2021,
        tracks: [
          ['Harbour Lights', 214],
          ['Saltwater Radio', 187],
          ['Undertow', 243],
          ['Lantern Weather', 201],
        ],
      },
      {
        id: 'al-2',
        name: 'Paper Satellites',
        year: 2023,
        tracks: [
          ['Orbit for Two', 198],
          ['Static Bloom', 226],
          ['Night Ferry', 265],
        ],
      },
    ],
  },
  {
    id: 'ar-2',
    name: 'The Quiet Engines',
    albums: [
      {
        id: 'al-3',
        name: 'Copper & Coal',
        year: 2019,
        tracks: [
          ['Foundry Song', 176],
          ['Iron Lung Blues', 233],
          ['Slow Furnace', 289],
          ['Railyard at Dawn', 205],
          ['Smoke Signals', 191],
        ],
      },
    ],
  },
  {
    id: 'ar-3',
    name: 'Mira Okonkwo',
    albums: [
      {
        id: 'al-4',
        name: 'Garden of Small Hours',
        year: 2024,
        tracks: [
          ['First Light', 162],
          ['Fig Tree', 218],
          ['Small Hours', 247],
        ],
      },
    ],
  },
  {
    id: 'ar-4',
    name: 'Velvet Cartography',
    albums: [
      {
        id: 'al-5',
        name: 'Maps of Nowhere',
        year: 2018,
        tracks: [
          ['Compass Rose', 231],
          ['Terra Incognita', 302],
          ['Here Be Dragons', 274],
          ['Meridian', 196],
        ],
      },
    ],
  },
]

export const songs: Song[] = []
export const albums: Album[] = []
export const artists: Artist[] = []

for (const a of seeds) {
  const artistAlbums: AlbumSummary[] = []
  for (const al of a.albums) {
    const albumSongs: Song[] = al.tracks.map(([title, duration], i) => ({
      id: `${al.id}-t${i + 1}`,
      title,
      artist: a.name,
      artistId: a.id,
      album: al.name,
      albumId: al.id,
      track: i + 1,
      year: al.year,
      duration,
      coverArt: al.id,
      suffix: 'mp3',
      starred: false,
    }))
    const summary: AlbumSummary = {
      id: al.id,
      name: al.name,
      artist: a.name,
      artistId: a.id,
      year: al.year,
      songCount: albumSongs.length,
      duration: albumSongs.reduce((s, x) => s + x.duration, 0),
      coverArt: al.id,
    }
    songs.push(...albumSongs)
    albums.push({ ...summary, songs: albumSongs })
    artistAlbums.push(summary)
  }
  artists.push({ id: a.id, name: a.name, albumCount: artistAlbums.length, coverArt: a.albums[0]?.id, albums: artistAlbums })
}

export function toAlbumSummary({ songs: _songs, ...rest }: Album): AlbumSummary {
  return rest
}

export function toArtistSummary({ albums: _albums, ...rest }: Artist): ArtistSummary {
  return rest
}
