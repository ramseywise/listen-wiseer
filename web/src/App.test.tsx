import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'
import { createHandlers } from './mocks/handlers'
import { usePlayback } from './player/audio'
import { usePlayer } from './player/playerStore'
import { initialQueueState } from './player/queue'
import { setupMockServer } from './test/server'

const server = setupMockServer()

function renderAt(path: string) {
  window.history.pushState({}, '', path)
  return render(<App />)
}

const playerBar = () => screen.getByRole('contentinfo', { name: 'Player' })

beforeEach(() => {
  usePlayer.setState(initialQueueState)
  usePlayback.setState({ intent: false, isPlaying: false, currentTime: 0, duration: 0 })
})

describe('App', () => {
  it('renders album rows on Home', async () => {
    renderAt('/')
    expect(await screen.findByText('Newly added')).toBeInTheDocument()
    expect((await screen.findAllByText('Garden of Small Hours')).length).toBeGreaterThan(0)
  })

  it('shows an intentional empty state for an empty library', async () => {
    server.use(...createHandlers('empty'))
    renderAt('/')
    expect(await screen.findByText('Your library is ready for music')).toBeInTheDocument()
  })

  it('shows library offline on 503', async () => {
    server.use(...createHandlers('offline'))
    renderAt('/library')
    expect(await screen.findByText('Library offline')).toBeInTheDocument()
  })

  it('plays an album and keeps playing across navigation', async () => {
    const user = userEvent.setup()
    renderAt('/album/al-3')
    await screen.findByRole('heading', { name: 'Copper & Coal' })
    await user.click(within(screen.getByRole('main')).getByRole('button', { name: /^Play$/ }))
    expect(within(playerBar()).getByText('Foundry Song')).toBeInTheDocument()
    expect(usePlayer.getState().queue).toHaveLength(5)

    const audio = screen.getByTestId('audio-engine') as HTMLAudioElement
    expect(audio.getAttribute('src')).toBe('/api/stream/al-3-t1')

    await user.click(screen.getAllByRole('link', { name: /Library/ })[0]!)
    await screen.findByRole('heading', { name: 'Library' })
    expect(within(playerBar()).getByText('Foundry Song')).toBeInTheDocument()
    expect(screen.getByTestId('audio-engine')).toBe(audio)
  })

  it('shuffle album turns shuffle on', async () => {
    const user = userEvent.setup()
    renderAt('/album/al-1')
    await screen.findByRole('heading', { name: 'Low Tide Signals' })
    await user.click(within(screen.getByRole('main')).getByRole('button', { name: /Shuffle/ }))
    expect(usePlayer.getState().shuffle).toBe(true)
    expect(usePlayer.getState().queue).toHaveLength(4)
  })

  it('toasts and skips when a track fails to load', async () => {
    const user = userEvent.setup()
    renderAt('/album/al-3')
    await screen.findByRole('heading', { name: 'Copper & Coal' })
    await user.click(within(screen.getByRole('main')).getByRole('button', { name: /^Play$/ }))
    act(() => {
      fireEvent.error(screen.getByTestId('audio-engine'))
    })
    expect(await screen.findByText(/Couldn't play "Foundry Song"/)).toBeInTheDocument()
    expect(within(playerBar()).getByText('Iron Lung Blues')).toBeInTheDocument()
  })

  it('stops after every track has failed', async () => {
    const user = userEvent.setup()
    renderAt('/album/al-4')
    await screen.findByRole('heading', { name: 'Garden of Small Hours' })
    await user.click(within(screen.getByRole('main')).getByRole('button', { name: /^Play$/ }))
    for (let i = 0; i < 3; i++) {
      act(() => {
        fireEvent.error(screen.getByTestId('audio-engine'))
      })
    }
    expect(usePlayer.getState().index).toBe(2)
    expect(usePlayback.getState().intent).toBe(false)
    expect(await screen.findByText('Playback stopped.')).toBeInTheDocument()
  })

  it('adds a track to the queue from the row menu', async () => {
    const user = userEvent.setup()
    renderAt('/album/al-2')
    await screen.findByRole('heading', { name: 'Paper Satellites' })
    await user.click(screen.getByRole('button', { name: /More options for Night Ferry/ }))
    expect(screen.getByRole('menuitem', { name: /Add to playlist/ })).not.toHaveAttribute('data-disabled')
    await user.click(screen.getByRole('menuitem', { name: /Add to queue/ }))
    expect(usePlayer.getState().queue.map((q) => (q.kind === 'library' ? q.song.title : ''))).toEqual(['Night Ferry'])
  })

  it('searches with debounce', async () => {
    const user = userEvent.setup()
    renderAt('/search')
    await user.type(screen.getByRole('searchbox', { name: 'Search library' }), 'harbour')
    expect(await screen.findByText('Harbour Lights')).toBeInTheDocument()
    expect(window.location.search).toBe('?q=harbour')
  })

  it('persists the assistant panel state', async () => {
    const user = userEvent.setup()
    renderAt('/')
    await user.click(within(playerBar()).getAllByRole('button', { name: 'Assistant' })[0]!)
    await waitFor(() => expect(screen.getByRole('complementary', { name: 'Assistant' })).toBeInTheDocument())
    expect(window.localStorage.getItem('lw:assistantOpen')).toBe('true')
  })
})
