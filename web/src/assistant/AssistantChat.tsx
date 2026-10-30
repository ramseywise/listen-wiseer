import { ArrowUp, Check, ListMusic, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import Markdown from 'react-markdown'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { type AssistantMessage, type ChatMessage, type InterruptState, useChat } from './chatStore'
import { TrackCards } from './TrackCard'

/** Same greeting the old chat UI opened with. */
export const WELCOME = `Welcome to **listen-wiseer**! 🎵

I can help you:
- **Discover music** — *"find me tracks like Radiohead's Reckoner"*
- **Listen** — *"play Weird Fishes"* (your library, or 30s previews + YouTube)
- **Explore your history** — *"what have I been listening to?"*
- **Genre deep dives** — *"tell me about the origins of bossa nova"*
- **Save a playlist** — *"save those as a playlist"*

What would you like to do?`

const STARTERS = ['More like what’s playing', 'What is this track?', 'Build me a late-night playlist']

function Prose({ text }: { text: string }) {
  return (
    <div
      className={cn(
        'space-y-2 text-sm leading-relaxed break-words',
        '[&_ul]:list-disc [&_ul]:space-y-0.5 [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:space-y-0.5 [&_ol]:pl-5',
        '[&_a]:text-violet [&_a]:underline [&_strong]:font-semibold [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold',
        '[&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:text-xs',
      )}
    >
      <Markdown
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </Markdown>
    </div>
  )
}

function InterruptCard({ interrupt, onAnswer, disabled }: { interrupt: InterruptState; onAnswer: (yes: boolean) => void; disabled: boolean }) {
  const tracks = `${interrupt.trackCount} track${interrupt.trackCount === 1 ? '' : 's'}`
  return (
    <div role="group" aria-label="Confirm playlist" className="space-y-2 rounded-lg border border-violet/40 bg-violet/10 p-3">
      <div className="flex items-start gap-2 text-sm">
        <ListMusic className="mt-0.5 size-4 shrink-0 text-violet" />
        <span>
          Save playlist <strong>“{interrupt.name}”</strong> ({tracks}) to your library?
        </span>
      </div>
      {interrupt.status === 'pending' ? (
        <div className="flex gap-2">
          <Button size="sm" onClick={() => onAnswer(true)} disabled={disabled}>
            <Check /> Yes, save it
          </Button>
          <Button size="sm" variant="outline" onClick={() => onAnswer(false)} disabled={disabled}>
            <X /> No
          </Button>
        </div>
      ) : (
        <div className="text-xs text-muted-foreground">{interrupt.status === 'confirmed' ? 'Confirmed' : 'Cancelled'}</div>
      )}
    </div>
  )
}

function AssistantBubble({ msg }: { msg: AssistantMessage }) {
  const answer = useChat((s) => s.answer)
  const busy = useChat((s) => s.busy)
  const thinking = msg.streaming && !msg.text
  return (
    <div className="space-y-2.5" aria-busy={msg.streaming}>
      {thinking ? (
        <div className="flex gap-1 py-1" role="status" aria-label="Assistant is thinking">
          {[0, 1, 2].map((i) => (
            <span key={i} className="size-1.5 animate-pulse rounded-full bg-muted-foreground" style={{ animationDelay: `${i * 150}ms` }} />
          ))}
        </div>
      ) : null}
      {msg.text ? <Prose text={msg.text} /> : null}
      {msg.tracks.length ? <TrackCards tracks={msg.tracks} /> : null}
      {msg.interrupt ? <InterruptCard interrupt={msg.interrupt} onAnswer={(yes) => void answer(yes)} disabled={busy} /> : null}
      {msg.error ? (
        <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {msg.error}
        </div>
      ) : null}
    </div>
  )
}

function Message({ msg }: { msg: ChatMessage }) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-3 py-2 text-sm whitespace-pre-wrap text-primary-foreground">
          {msg.text}
        </div>
      </div>
    )
  }
  return <AssistantBubble msg={msg} />
}

function Chips({ items, onPick, disabled }: { items: string[]; onPick: (s: string) => void; disabled: boolean }) {
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Suggestions">
      {items.map((s) => (
        <button
          key={s}
          type="button"
          disabled={disabled}
          onClick={() => onPick(s)}
          className="rounded-full border px-3 py-1 text-left text-xs text-muted-foreground transition-colors hover:border-violet/50 hover:text-foreground disabled:opacity-50"
        >
          {s}
        </button>
      ))}
    </div>
  )
}

function Composer({ onSend, disabled }: { onSend: (text: string) => void; disabled: boolean }) {
  const [text, setText] = useState('')
  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    if (!text.trim() || disabled) return
    onSend(text)
    setText('')
  }
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) submit(e)
  }
  return (
    <form onSubmit={submit} className="flex items-end gap-2 border-t p-3">
      <textarea
        aria-label="Message the assistant"
        placeholder="Ask about music…"
        rows={1}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        className="max-h-32 min-h-9 flex-1 resize-none rounded-lg border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
      />
      <Button type="submit" size="icon" aria-label="Send" disabled={disabled || !text.trim()}>
        <ArrowUp />
      </Button>
    </form>
  )
}

export function AssistantChat() {
  const messages = useChat((s) => s.messages)
  const busy = useChat((s) => s.busy)
  const send = useChat((s) => s.send)
  const scroller = useRef<HTMLDivElement>(null)

  const last = messages.at(-1)
  const pendingInterrupt = last?.role === 'assistant' && last.interrupt?.status === 'pending'
  const chips =
    messages.length === 0 ? STARTERS : last?.role === 'assistant' && !last.streaming && !pendingInterrupt ? last.suggestions : []

  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight })
  }, [messages])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scroller} className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4" role="log" aria-label="Conversation">
        {messages.length === 0 ? <Prose text={WELCOME} /> : null}
        {messages.map((m) => (
          <Message key={m.id} msg={m} />
        ))}
        {chips.length ? <Chips items={chips} onPick={(s) => void send(s)} disabled={busy} /> : null}
      </div>
      <Composer onSend={(t) => void send(t)} disabled={busy || pendingInterrupt} />
    </div>
  )
}
