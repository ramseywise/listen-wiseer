import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { ChatEvent, ChatRequest, ChatTrack, TrackBrief } from '@/api/types'
import { usePlayer } from '@/player/playerStore'
import { currentItem, itemArtist, itemTitle, upNext, type QueueItem } from '@/player/queue'
import { resumeChat, streamChat } from './chatApi'

export type InterruptState = {
  kind: 'confirm_playlist_create'
  name: string
  trackCount: number
  status: 'pending' | 'confirmed' | 'cancelled'
}

export type UserMessage = { id: string; role: 'user'; text: string }

export type AssistantMessage = {
  id: string
  role: 'assistant'
  text: string
  streaming: boolean
  tracks: ChatTrack[]
  suggestions: string[]
  interrupt?: InterruptState
  error?: string
}

export type ChatMessage = UserMessage | AssistantMessage

type ChatState = {
  threadId: string | null
  messages: ChatMessage[]
  busy: boolean
  send: (text: string) => Promise<void>
  answer: (confirmed: boolean) => Promise<void>
  newChat: () => void
}

export const UP_NEXT_LIMIT = 5

let seq = 0
const newId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(seq++).toString(36)}`

let controller: AbortController | null = null

function brief(item: QueueItem): TrackBrief {
  const album = item.kind === 'library' ? item.song.album : undefined
  return { artist: itemArtist(item), title: itemTitle(item), ...(album ? { album } : {}) }
}

/** What's playing + the next few, sent with each message as context (not as chat text). */
export function playerContext(): Pick<ChatRequest, 'nowPlaying' | 'upNext'> {
  const state = usePlayer.getState()
  const now = currentItem(state)
  const next = upNext(state).slice(0, UP_NEXT_LIMIT).map(brief)
  return { ...(now ? { nowPlaying: brief(now) } : {}), ...(next.length ? { upNext: next } : {}) }
}

/** Fold one ChatEvent into the assistant message it belongs to. */
export function applyEvent(msg: AssistantMessage, event: ChatEvent): AssistantMessage {
  switch (event.type) {
    case 'thread':
      return msg
    case 'token':
      return { ...msg, text: msg.text + event.text }
    case 'tracks':
      return { ...msg, tracks: event.tracks }
    case 'suggestions':
      return { ...msg, suggestions: event.items }
    case 'interrupt':
      return {
        ...msg,
        streaming: false,
        interrupt: { kind: event.kind, name: event.name, trackCount: event.trackCount, status: 'pending' },
      }
    case 'done':
      // the final text supersedes the streamed draft (e.g. after a verifier retry)
      return { ...msg, streaming: false, text: event.message || msg.text }
    case 'error':
      return { ...msg, streaming: false, error: event.detail }
  }
}

export const useChat = create<ChatState>()(
  persist(
    (set, get) => {
      /** Stream one turn into a fresh assistant message. */
      async function run(start: (onEvent: (e: ChatEvent) => void, signal: AbortSignal) => Promise<void>) {
        controller?.abort()
        const ctrl = new AbortController()
        controller = ctrl
        const id = newId('a')
        const placeholder: AssistantMessage = {
          id, role: 'assistant', text: '', streaming: true, tracks: [], suggestions: [],
        } // prettier-ignore
        set((s) => ({ busy: true, messages: [...s.messages, placeholder] }))

        const update = (fn: (m: AssistantMessage) => AssistantMessage) =>
          set((s) => ({
            messages: s.messages.map((m) => (m.id === id && m.role === 'assistant' ? fn(m) : m)),
          }))

        try {
          await start((event) => {
            if (ctrl.signal.aborted) return
            if (event.type === 'thread') set({ threadId: event.threadId })
            update((m) => applyEvent(m, event))
          }, ctrl.signal)
          // stream closed without a terminal event (proxy cut it, server crash…)
          update((m) => (m.streaming ? { ...m, streaming: false, error: m.text ? undefined : 'No reply — please try again.' } : m))
        } catch (err) {
          if (err instanceof DOMException && err.name === 'AbortError') return
          update((m) => ({ ...m, streaming: false, error: 'Something went wrong — please try again.' }))
        } finally {
          if (controller === ctrl) {
            controller = null
            set({ busy: false })
          }
        }
      }

      return {
        threadId: null,
        messages: [],
        busy: false,

        send: async (text) => {
          const message = text.trim()
          if (!message || get().busy) return
          set((s) => ({ messages: [...s.messages, { id: newId('u'), role: 'user', text: message }] }))
          const threadId = get().threadId ?? undefined
          const request: ChatRequest = { ...(threadId ? { threadId } : {}), message, ...playerContext() }
          await run((onEvent, signal) => streamChat(request, onEvent, signal))
        },

        answer: async (confirmed) => {
          const { threadId, messages, busy } = get()
          const target = [...messages].reverse().find((m) => m.role === 'assistant' && m.interrupt?.status === 'pending')
          if (!threadId || !target || busy) return
          set((s) => ({
            messages: s.messages.map((m) =>
              m.id === target.id && m.role === 'assistant' && m.interrupt
                ? { ...m, interrupt: { ...m.interrupt, status: confirmed ? 'confirmed' : 'cancelled' } }
                : m,
            ),
          }))
          await run((onEvent, signal) => resumeChat(threadId, confirmed, onEvent, signal))
        },

        newChat: () => {
          controller?.abort()
          controller = null
          set({ threadId: null, messages: [], busy: false })
        },
      }
    },
    {
      name: 'lw:chat',
      storage: createJSONStorage(() => sessionStorage),
      // a half-streamed reply can't resume after a reload; keep what arrived
      partialize: (s) => ({
        threadId: s.threadId,
        messages: s.messages.map((m) => (m.role === 'assistant' && m.streaming ? { ...m, streaming: false } : m)),
      }),
    },
  ),
)
