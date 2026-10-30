import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'
import { createHandlers } from './mocks/handlers'
import { songs } from './mocks/fixtures'
import { usePlayback } from './player/audio'
import { usePlayer } from './player/playerStore'
import { initialQueueState, itemTitle } from './player/queue'
import { useNewPlaylistDialog } from './playlists/newPlaylist'
import { setupMockServer } from './test/server'

const server = setupMockServer()

function renderAt(path: string) {
  window.history.pushState({}, '', path)
  return render(<App />)
}

const main = () => screen.getByRole('main')
const playerBar = () => screen.getByRole('contentinfo', { name: 'Player' })
const queueTitles = () => usePlayer.getState().queue.map(itemTitle)

beforeEach(() => {
  // fresh mock library state (playlists, likes, saved queue) per test
  server.use(...createHandlers('full'))
  usePlayer.setState(initialQueueState)
  usePlayback.setState({ intent: false, isPlaying: false, currentTime: 0, duration: 0 })
  useNewPlaylistDialog.setState({ open: false, songIds: [] })
})

describe('playlists', () => {
  it('creates a playlist from a track menu', async () => {
    const user = userEvent.setup()
    renderAt('/album/al-2')
    await screen.findByRole('heading', { name: 'Paper Satellites' })
    await user.click(screen.getByRole('button', { name: /More options for Night Ferry/ }))
    await user.click(screen.getByRole('menuitem', { name: /Add to playlist/ }))
    // Radix closes a submenu on pointer-leave when it can't measure layout (jsdom), so select without moving the pointer
    fireEvent.click(await screen.findByRole('menuitem', { name: /New playlist/ }))
    const dialog = await screen.findByRole('dialog', { name: 'New playlist' })
    expect(within(dialog).getByText('Starts with 1 song.')).toBeInTheDocument()
    await user.type(within(dialog).getByRole('textbox', { name: 'Playlist name' }), 'Late Boats')
    await user.click(within(dialog).getByRole('button', { name: 'Create' }))
    expect(await screen.findByText('Created "Late Boats"')).toBeInTheDocument()

    await user.click(screen.getAllByRole('link', { name: /^Playlists$/ })[0]!)
    await user.click(await within(main()).findByRole('link', { name: /Late Boats/ }))
    expect(await within(main()).findByRole('heading', { name: 'Late Boats' })).toBeInTheDocument()
    expect(within(main()).getAllByTestId('playlist-row').map((r) => r.textContent)).toEqual([
      expect.stringContaining('Night Ferry'),
    ])
  })

  it('adds a track to an existing playlist', async () => {
    const user = userEvent.setup()
    renderAt('/album/al-3')
    await screen.findByRole('heading', { name: 'Copper & Coal' })
    await user.click(screen.getByRole('button', { name: /More options for Foundry Song/ }))
    await user.click(screen.getByRole('menuitem', { name: /Add to playlist/ }))
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Evening Mix' }))
    expect(await screen.findByText('Added to Evening Mix')).toBeInTheDocument()

    await user.click(screen.getAllByRole('link', { name: /^Playlists$/ })[0]!)
    await user.click(await within(main()).findByRole('link', { name: /Evening Mix/ }))
    await waitFor(() => expect(within(main()).getAllByTestId('playlist-row')).toHaveLength(3))
    expect(within(main()).getAllByTestId('playlist-row')[2]).toHaveTextContent('Foundry Song')
  })

  it('plays, removes, renames and deletes on the playlist page', async () => {
    const user = userEvent.setup()
    renderAt('/playlist/pl-1')
    await within(main()).findByRole('heading', { name: 'Evening Mix' })
    expect(within(main()).getAllByTestId('playlist-row')).toHaveLength(2)

    await user.click(within(main()).getByRole('button', { name: /^Play$/ }))
    expect(queueTitles()).toEqual(['Saltwater Radio', 'First Light'])
    expect(within(playerBar()).getByText('Saltwater Radio')).toBeInTheDocument()

    await user.click(within(main()).getByRole('button', { name: /More options for Saltwater Radio/ }))
    await user.click(screen.getByRole('menuitem', { name: /Remove from this playlist/ }))
    await waitFor(() => expect(within(main()).getAllByTestId('playlist-row')).toHaveLength(1))
    expect(within(main()).getByTestId('playlist-row')).toHaveTextContent('First Light')

    await user.click(within(main()).getByRole('button', { name: 'Rename playlist' }))
    const rename = await screen.findByRole('dialog', { name: 'Rename playlist' })
    const field = within(rename).getByRole('textbox', { name: 'Playlist name' })
    expect(field).toHaveValue('Evening Mix')
    await user.clear(field)
    await user.type(field, 'Night Mix{Enter}')
    expect(await within(main()).findByRole('heading', { name: 'Night Mix' })).toBeInTheDocument()

    await user.click(within(main()).getByRole('button', { name: 'Delete playlist' }))
    const confirm = await screen.findByRole('dialog')
    await user.click(within(confirm).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(window.location.pathname).toBe('/playlists'))
    await waitFor(() => expect(within(main()).queryByRole('link', { name: /Night Mix/ })).not.toBeInTheDocument())
  })
})

describe('likes', () => {
  it('likes from the player bar and lists it under Liked Songs', async () => {
    const user = userEvent.setup()
    renderAt('/album/al-2')
    await screen.findByRole('heading', { name: 'Paper Satellites' })
    await user.click(within(main()).getByRole('button', { name: /^Play$/ }))
    const like = await within(playerBar()).findByRole('button', { name: 'Like Orbit for Two' })
    expect(like).toHaveAttribute('aria-pressed', 'false')
    await user.click(like)
    expect(await within(playerBar()).findByRole('button', { name: 'Unlike Orbit for Two' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )

    await user.click(screen.getAllByRole('link', { name: /Liked Songs/ })[0]!)
    await within(main()).findByRole('heading', { name: 'Liked Songs' })
    expect(await within(main()).findByText('Orbit for Two')).toBeInTheDocument()
    expect(within(main()).getByText('Compass Rose')).toBeInTheDocument()

    await user.click(within(playerBar()).getByRole('button', { name: 'Unlike Orbit for Two' }))
    await waitFor(() => expect(within(main()).queryByText('Orbit for Two')).not.toBeInTheDocument())
  })

  it('likes from the track menu', async () => {
    const user = userEvent.setup()
    renderAt('/album/al-4')
    await screen.findByRole('heading', { name: 'Garden of Small Hours' })
    await user.click(screen.getByRole('button', { name: /More options for Fig Tree/ }))
    await user.click(screen.getByRole('menuitem', { name: /^Like$/ }))
    await user.click(screen.getByRole('button', { name: /More options for Fig Tree/ }))
    expect(await screen.findByRole('menuitem', { name: /^Unlike$/ })).toBeInTheDocument()
  })
})

describe('archive', () => {
  it('lists archived playlists with track counts', async () => {
    renderAt('/archive')
    const link = await within(main()).findByRole('link', { name: /Road Trip 2019/ })
    expect(link).toHaveTextContent('7 tracks')
    expect(within(main()).getByRole('link', { name: /Untitled/ })).toHaveTextContent('0 tracks')
  })

  it('plays by resolving only a few tracks ahead', async () => {
    const user = userEvent.setup()
    renderAt('/archive/sp-1')
    await within(main()).findByRole('heading', { name: 'Road Trip 2019' })
    const rows = within(main()).getAllByTestId('archive-row')
    expect(rows).toHaveLength(7)

    await user.click(within(main()).getByRole('button', { name: /^Play$/ }))
    // Harbour Lights + 3 ahead (Ghost Song preview, Unfindable skipped, Foundry Song, Fig Tree)
    await waitFor(() => expect(queueTitles()).toEqual(['Harbour Lights', 'Ghost Song', 'Foundry Song', 'Fig Tree']))
    expect(usePlayer.getState().queue.map((q) => q.kind)).toEqual(['library', 'preview', 'library', 'library'])
    expect(within(playerBar()).getByText('Harbour Lights')).toBeInTheDocument()

    expect(within(rows[0]!).getByText('library')).toBeInTheDocument()
    expect(within(rows[1]!).getByText('preview')).toBeInTheDocument()
    expect(within(rows[2]!).getByRole('link', { name: /YouTube/ })).toHaveAttribute(
      'href',
      'https://www.youtube.com/watch?v=mock',
    )
    // not resolved yet: no badge on the tail
    expect(within(rows[5]!).queryByText(/library|preview|YouTube/)).not.toBeInTheDocument()
    expect(within(rows[6]!).queryByText(/library|preview|YouTube/)).not.toBeInTheDocument()

    usePlayer.getState().next()
    await waitFor(() => expect(queueTitles()).toContain('Deep Cut'))
  })

  it('copies to a library playlist and reports the unmatched tracks', async () => {
    const user = userEvent.setup()
    renderAt('/archive/sp-1')
    await within(main()).findByRole('heading', { name: 'Road Trip 2019' })
    await user.click(within(main()).getByRole('button', { name: /Copy to library playlist/ }))
    const note = await within(main()).findByRole('status')
    expect(note).toHaveTextContent('Copied to Road Trip 2019 with 4 tracks.')
    expect(note).toHaveTextContent('3 tracks not in your library')
    expect(within(note).getByRole('link', { name: 'Road Trip 2019' })).toHaveAttribute(
      'href',
      expect.stringMatching(/^\/playlist\/pl-/),
    )
  })
})

describe('queue persistence', () => {
  it('restores the saved queue paused', async () => {
    const saved = songs.filter((s) => s.albumId === 'al-3').slice(0, 3)
    server.use(
      http.get('/api/player/queue', () =>
        HttpResponse.json({ songs: saved, songIds: saved.map((s) => s.id), current: saved[1]!.id, position: 42 }),
      ),
    )
    renderAt('/')
    await waitFor(() => expect(queueTitles()).toEqual(saved.map((s) => s.title)))
    expect(usePlayer.getState().index).toBe(1)
    expect(usePlayback.getState().intent).toBe(false)
    expect(within(playerBar()).getByText(saved[1]!.title)).toBeInTheDocument()
  })

  it('leaves an existing local queue alone', async () => {
    const saved = songs.slice(0, 2)
    server.use(
      http.get('/api/player/queue', () =>
        HttpResponse.json({ songs: saved, songIds: saved.map((s) => s.id), position: 0 }),
      ),
    )
    const local = songs.find((s) => s.title === 'Meridian')!
    usePlayer.getState().playNow([{ kind: 'library', song: local }])
    renderAt('/')
    await screen.findByText('Newly added')
    expect(queueTitles()).toEqual(['Meridian'])
  })
})
