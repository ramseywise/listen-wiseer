import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { makeQueryClient } from '@/api/queryClient'
import type { ChatRequest, Song } from '@/api/types'
import { songs } from '@/mocks/fixtures'
import { usePlayer } from '@/player/playerStore'
import { initialQueueState } from '@/player/queue'
import { setupMockServer } from '@/test/server'
import { AssistantChat } from './AssistantChat'
import { useChat } from './chatStore'

const server = setupMockServer()
const [s0, s1, s2] = songs as [Song, Song, Song, ...Song[]]

function renderChat() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <AssistantChat />
    </QueryClientProvider>,
  )
}

async function say(text: string) {
  const user = userEvent.setup()
  await user.type(screen.getByRole('textbox', { name: 'Message the assistant' }), `${text}{Enter}`)
  return user
}

beforeEach(() => {
  usePlayer.setState(initialQueueState)
  useChat.getState().newChat()
  sessionStorage.clear()
})

describe('AssistantChat', () => {
  it('shows the welcome message and starter chips', () => {
    renderChat()
    expect(screen.getByText(/What would you like to do\?/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'What is this track?' })).toBeInTheDocument()
  })

  it('streams a reply with track cards, suggestions and queue actions', async () => {
    renderChat()
    const user = await say('late night jazz')
    expect(await screen.findByText(/Here are a few picks/)).toBeInTheDocument()
    expect(screen.getByText('late night jazz')).toBeInTheDocument()

    const first = s0
    const card = screen.getByRole('listitem', { name: `${first.title} by ${first.artist}` })
    await user.click(within(card).getByRole('button', { name: `Play ${first.title} by ${first.artist}` }))
    expect(usePlayer.getState().queue.map((q) => q.kind === 'library' && q.song.id)).toEqual([first.id])

    const outsider = screen.getByRole('listitem', { name: 'Somewhere Else by Mock Outsider' })
    expect(within(outsider).getByText('Preview · not in library')).toBeInTheDocument()
    expect(within(outsider).getByRole('link', { name: /on YouTube/ })).toHaveAttribute(
      'href',
      'https://www.youtube.com/watch?v=mock',
    )

    await user.click(screen.getByRole('button', { name: 'Queue all (3)' }))
    const queue = usePlayer.getState().queue
    expect(queue).toHaveLength(4)
    expect(queue.at(-1)).toMatchObject({ kind: 'preview', url: 'https://cdn.example.test/preview.mp3' })

    expect(screen.getByRole('button', { name: 'Want to save any of these to a playlist?' })).toBeInTheDocument()
    expect(useChat.getState().threadId).toMatch(/^mock-thread-/)
  })

  it('sends now-playing and up-next as context and keeps the thread id', async () => {
    const bodies: ChatRequest[] = []
    server.events.on('request:start', async ({ request }) => {
      if (request.url.endsWith('/api/chat')) bodies.push((await request.clone().json()) as ChatRequest)
    })
    usePlayer.getState().playNow(songs.slice(0, 3).map((song) => ({ kind: 'library', song })))
    renderChat()
    await say('more like this')
    expect(await screen.findByText(/Since you're playing/)).toBeInTheDocument()
    await say('and again')
    await waitFor(() => expect(bodies).toHaveLength(2))
    expect(bodies[0]).toMatchObject({
      message: 'more like this',
      nowPlaying: { artist: s0.artist, title: s0.title, album: s0.album },
      upNext: [
        { artist: s1.artist, title: s1.title },
        { artist: s2.artist, title: s2.title },
      ],
    })
    expect(bodies[0]?.threadId).toBeUndefined()
    expect(bodies[1]?.threadId).toBe(useChat.getState().threadId)
    server.events.removeAllListeners()
  })

  it('confirms a playlist save through the interrupt card', async () => {
    const resumes: unknown[] = []
    server.events.on('request:start', async ({ request }) => {
      if (request.url.endsWith('/api/chat/resume')) resumes.push(await request.clone().json())
    })
    renderChat()
    const user = await say('save these as a playlist')
    const card = await screen.findByRole('group', { name: 'Confirm playlist' })
    expect(card).toHaveTextContent('Save playlist “Mock Mix” (3 tracks) to your library?')
    expect(screen.getByRole('textbox', { name: 'Message the assistant' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()

    await user.click(within(card).getByRole('button', { name: /Yes, save it/ }))
    expect(await screen.findByText(/2 of 3 tracks matched/)).toBeInTheDocument()
    expect(within(card).getByText('Confirmed')).toBeInTheDocument()
    expect(resumes).toEqual([{ threadId: useChat.getState().threadId, confirmed: true }])
    server.events.removeAllListeners()
  })

  it('declining the interrupt resumes with confirmed=false', async () => {
    renderChat()
    const user = await say('save it')
    const card = await screen.findByRole('group', { name: 'Confirm playlist' })
    await user.click(within(card).getByRole('button', { name: /No/ }))
    expect(await screen.findByText(/won’t save it/)).toBeInTheDocument()
    expect(within(card).getByText('Cancelled')).toBeInTheDocument()
  })

  it('shows an error event as an alert and re-enables input', async () => {
    server.use(
      http.post('/api/chat', () =>
        new HttpResponse(
          'data: {"type":"thread","threadId":"t9"}\n\ndata: {"type":"error","detail":"Something went wrong — please try again."}\n\n',
          { headers: { 'Content-Type': 'text/event-stream' } },
        ),
      ),
    )
    renderChat()
    await say('hello')
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
    await waitFor(() => expect(useChat.getState().busy).toBe(false))
  })

  it('New chat clears the conversation and thread', async () => {
    renderChat()
    await say('jazz')
    await screen.findByText(/Here are a few picks/)
    useChat.getState().newChat()
    await waitFor(() => expect(screen.getByText(/What would you like to do\?/)).toBeInTheDocument())
    expect(useChat.getState().threadId).toBeNull()
  })
})
