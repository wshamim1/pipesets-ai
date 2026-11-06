// Public chat links (/c/<token>): the calls a visitor's page makes to /v1/chat (backend routers/chat_links.py).
// No sign-in — the token in the URL is the credential. Kept free of the builder's code so the page stays small.

import { PUBLIC_API_BASE } from '../types'

/** What the link lets visitors see about the pipeline: names only, never prompts or credentials. */
export interface ChatAbout {
  pipeline_id: string
  version: number
  description: string
  models: string[]
  tools: string[]
  mcp_servers: string[]
  agents: string[]
  pipelines: string[]
  answers_from_documents: boolean
}

export interface ChatSession {
  session: string
  resumed: boolean
  title: string
  greeting: string
  starter_prompts: string[]
  about: ChatAbout | null
  max_message_chars: number
}

export type ChatEvent =
  | { type: 'token'; text: string }
  | { type: 'error'; message: string; retract?: boolean }
  | { type: 'done'; feedback?: string }

export class ChatError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** The link's token from a /c/<token> path. */
export function tokenFromPath(pathname: string): string | null {
  const m = pathname.match(/\/c\/([A-Za-z0-9_-]+)\/?$/)
  return m ? m[1] : null
}

const url = (token: string, path: string) => `${PUBLIC_API_BASE}/v1/chat/${encodeURIComponent(token)}/${path}`

async function failure(r: Response): Promise<ChatError> {
  const d = await r.json().catch(() => ({}))
  const fallback = r.status === 429 ? 'Too many messages — try again shortly' : 'Something went wrong — try again'
  return new ChatError(r.status, typeof d.detail === 'string' ? d.detail : fallback)
}

export async function startSession(token: string, previous = ''): Promise<ChatSession> {
  const r = await fetch(url(token, 'session'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session: previous }),
  })
  if (!r.ok) throw await failure(r)
  return r.json()
}

/** Split an SSE buffer into complete events and the unfinished rest. */
export function parseSse(buffer: string): { events: ChatEvent[]; rest: string } {
  const parts = buffer.split('\n\n')
  const rest = parts.pop() ?? ''
  const events: ChatEvent[] = []
  for (const part of parts) {
    for (const line of part.split('\n')) {
      if (!line.startsWith('data: ')) continue
      try {
        events.push(JSON.parse(line.slice(6)))
      } catch {
        // a malformed line is skipped, the stream goes on
      }
    }
  }
  return { events, rest }
}

export async function sendMessage(
  token: string, session: string, message: string, onEvent: (ev: ChatEvent) => void, signal: AbortSignal,
): Promise<void> {
  const r = await fetch(url(token, 'message'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session, message }), signal,
  })
  if (!r.ok || !r.body) throw await failure(r)
  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const { events, rest } = parseSse(buffer)
    buffer = rest
    events.forEach(onEvent)
  }
  parseSse(buffer + '\n\n').events.forEach(onEvent)
}

/** 👍 (1) / 👎 (-1) on an answer, with the token its ``done`` event carried; rating again replaces it. */
export async function sendFeedback(
  token: string, session: string, feedback: string, rating: 1 | -1, comment = '',
): Promise<void> {
  const r = await fetch(url(token, 'feedback'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session, feedback, rating, comment }),
  })
  if (!r.ok) throw await failure(r)
}
