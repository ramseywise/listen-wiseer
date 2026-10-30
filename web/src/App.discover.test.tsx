import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import type { SavedQueueState } from './api/types'
import App from './App'
import { useUi } from './lib/uiStore'
import { createHandlers } from './mocks/handlers'
import { songs } from './mocks/fixtures'
import { usePlayback } from './player/audio'
import { usePlayer } from './player/playerStore'
import { initialQueueState, itemTitle } from './player/queue'
import { radio } from './radio/radio'
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
  server.use(...createHandlers('full'))
  usePlayer.setState(initialQueueState)
  usePlayback.setState({ intent: false, isPlaying: false, currentTime: 0, duration: 0 })
  radio.store.setState({ enabled: false, loading: false })
  useUi.setState({ queueOpen: false })
})

describe('discover', () => {
  it('renders the three sections from the nav', async () => {
    const user = userEvent.setup()
    renderAt('/')
    await user.click(screen.getAllByRole('link', { name: /^Discover$/ })[0]!)
    expect(await within(main()).findByRole('heading', { name: 'Discover' })).toBeInTheDocument()
    const unplayed = await within(main()).findByRole('region', { name: 'In your library, not played yet' })
    expect(within(unplayed).getAllByTestId('discover-row')).toHaveLength(4)
    expect(within(unplayed).getAllByText('library')).toHaveLength(4)

    const fresh = within(main()).getByRole('region', { name: 'New to you' })
    expect(within(fresh).getByText('Ghost Song')).toBeInTheDocument()
    expect(within(fresh).getByText(/Similar on Deezer/)).toBeInTheDocument()

    const free = within(main()).getByRole('region', { name: 'Free to download' })
    const link = within(free).getByRole('link', { name: /Internet Archive/ })
    expect(link).toHaveAttribute('href', 'https://archive.org/details/oso')
  })

  it('plays a library row, and resolves an open-world row on demand', async () => {
    const user = userEvent.setup()
    renderAt('/discover')
    const unplayed = await within(main()).findByRole('region', { name: 'In your library, not played yet' })
    const last = songs.at(-1)!
    await user.click(within(unplayed).getByRole('button', { name: `Play ${last.title} — ${last.artist}` }))
    expect(queueTitles()).toEqual([last.title])

    const fresh = within(main()).getByRole('region', { name: 'New to you' })
    await user.click(within(fresh).getByRole('button', { name: /Add Ghost Song .* to queue/ }))
    await waitFor(() => expect(queueTitles()).toEqual([last.title, 'Ghost Song']))
    expect(usePlayer.getState().queue[1]?.kind).toBe('preview')

    await user.click(within(fresh).getByRole('button', { name: /Play Unplayable/ }))
    expect(await screen.findByText('Not playable here')).toBeInTheDocument()
  })

  it('shows an empty state when there is nothing to discover', async () => {
    server.use(...createHandlers('empty'))
    renderAt('/discover')
    expect(await within(main()).findByText('Nothing to discover yet')).toBeInTheDocument()
  })
})

describe('radio', () => {
  it('starts from a track menu: seed first, radio tracks marked in the queue', async () => {
    const user = userEvent.setup()
    renderAt('/album/al-2')
    await screen.findByRole('heading', { name: 'Paper Satellites' })
    await user.click(screen.getByRole('button', { name: /More options for Night Ferry/ }))
    await user.click(screen.getByRole('menuitem', { name: /Start radio/ }))
    await waitFor(() => expect(queueTitles()[0]).toBe('Night Ferry'))
    const queue = usePlayer.getState().queue
    expect(queue.length).toBeGreaterThan(1)
    expect(queue.slice(1).every((q) => q.radio)).toBe(true)
    expect(queueTitles().filter((t) => t === 'Night Ferry')).toHaveLength(1) // seed excluded
    expect(within(playerBar()).getByRole('button', { name: 'Autoplay similar: on' })).toHaveAttribute('aria-pressed', 'true')

    await user.click(within(playerBar()).getAllByRole('button', { name: /^Queue/ })[0]!)
    const upNext = await screen.findByRole('list', { name: 'Up next' })
    expect(within(upNext).getAllByText('radio').length).toBe(queue.length - 1)
  })

  it('autoplay toggle in the player bar refills a short queue', async () => {
    const user = userEvent.setup()
    renderAt('/')
    usePlayer.getState().playNow([{ kind: 'library', song: songs[0]! }])
    await user.click(within(playerBar()).getByRole('button', { name: 'Autoplay similar' }))
    await waitFor(() => expect(usePlayer.getState().queue.length).toBeGreaterThan(1))
    expect(usePlayer.getState().queue.slice(1).every((q) => q.radio)).toBe(true)
  })
})

describe('queue save on unload', () => {
  it('PUTs the queue with the current position on pagehide', async () => {
    const saved: SavedQueueState[] = []
    server.use(
      http.put('/api/player/queue', async ({ request }) => {
        saved.push((await request.json()) as SavedQueueState)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    renderAt('/')
    await screen.findByRole('main')
    usePlayer.setState({ ...initialQueueState, queue: [{ kind: 'library', song: songs[0]!, uid: 'u1' }], index: 0 })
    window.dispatchEvent(new Event('pagehide'))
    await waitFor(() => expect(saved).toEqual([{ songIds: [songs[0]!.id], current: songs[0]!.id, position: 0 }]))
  })
})

describe('mobile nav', () => {
  it('"More" opens playlists, likes and the archive; a link closes it', async () => {
    const user = userEvent.setup()
    renderAt('/')
    const mobile = screen.getAllByRole('navigation', { name: 'Main' }).at(-1)!
    await user.click(within(mobile).getByRole('button', { name: 'More' }))
    const sheet = await screen.findByRole('dialog', { name: 'Your music' })
    expect(within(sheet).getByRole('link', { name: 'Liked Songs' })).toBeInTheDocument()
    await user.click(within(sheet).getByRole('link', { name: 'Archive' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Your music' })).not.toBeInTheDocument())
    expect(await within(main()).findByRole('heading', { name: 'Archive' })).toBeInTheDocument()
  })
})
