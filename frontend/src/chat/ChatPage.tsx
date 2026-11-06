import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowUp, Check, Copy, ExternalLink, Info, Plus, Square, ThumbsDown, ThumbsUp } from 'lucide-react'
import { renderMarkdownBlock } from '../utils/renderMarkdown'
import { ChatError, sendFeedback, sendMessage, startSession, type ChatAbout, type ChatSession } from './chatApi'

interface Message {
  role: 'user' | 'assistant'
  content: string
  error?: boolean
  feedback?: string     // sealed token from the answer's done event: lets this visitor rate it
  rating?: 1 | -1
  commented?: boolean
}

interface Saved {
  session: string
  messages: Message[]
}

// The visitor's conversation survives a reload on this device; the server remembers it too (pipeline memory)
const storageKey = (token: string) => `pipesets-chat:${token}`

function load(token: string): Saved | null {
  try {
    const raw = localStorage.getItem(storageKey(token))
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function save(token: string, saved: Saved | null) {
  try {
    if (saved) localStorage.setItem(storageKey(token), JSON.stringify(saved))
    else localStorage.removeItem(storageKey(token))
  } catch {
    // storage unavailable (private mode): the chat still works until the page is closed
  }
}

/** An answer as the visitor should read it. Pipelines with a JSON output parser answer in JSON:
 *  a lone {"error": "..."} reads as its message, anything else as formatted JSON. */
function renderAnswer(content: string): ReactNode {
  const text = content.trim()
  if (/^[[{]/.test(text)) {
    try {
      const value = JSON.parse(text)
      const keys = value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value) : []
      if (keys.length === 1 && ['error', 'message', 'answer'].includes(keys[0]) && typeof value[keys[0]] === 'string')
        return renderMarkdownBlock(value[keys[0]])
      return renderMarkdownBlock('```json\n' + JSON.stringify(value, null, 2) + '\n```')
    } catch {
      // not JSON after all (still streaming, or prose that starts with a bracket)
    }
  }
  return renderMarkdownBlock(content)
}

const capabilities = (about: ChatAbout): [string, string[]][] => ([
  [about.models.length > 1 ? 'Models' : 'Model', about.models],
  ['Agents', about.agents],
  ['Tools', about.tools],
  [about.mcp_servers.length > 1 ? 'MCP servers' : 'MCP server', about.mcp_servers],
  ['Uses pipelines', about.pipelines],
] as [string, string[]][]).filter(([, items]) => items.length > 0)

// The builder UI: behind the edge proxy a different host than this page (VITE_UI_URL), else this origin
const UI_URL = import.meta.env.VITE_UI_URL || window.location.origin
const pipelineUrl = (id: string) => `${UI_URL}/?pipeline=${encodeURIComponent(id)}`

function PipelineInfo({ about }: { about: ChatAbout }) {
  const [copied, setCopied] = useState(false)
  const copy = () => navigator.clipboard?.writeText(about.pipeline_id)
    .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })
    .catch(() => {})
  return (
    <details className="cp-tech">
      <summary>Pipeline info</summary>
      <dl className="cp-tech-list">
        <div><dt>Pipeline ID</dt>
          <dd>
            <code>{about.pipeline_id}</code>
            <button type="button" className="cp-icon-btn" onClick={copy} aria-label="Copy pipeline ID">
              {copied ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
            </button>
          </dd>
        </div>
        {about.version > 0 && <div><dt>Version</dt><dd>v{about.version} (published)</dd></div>}
        <div><dt>Pipeline</dt>
          <dd>
            <a href={pipelineUrl(about.pipeline_id)} target="_blank" rel="noreferrer">
              Open in Pipesets <ExternalLink size={12} aria-hidden="true" />
            </a>
            <span className="cp-tech-hint">needs a Pipesets account with access</span>
          </dd>
        </div>
      </dl>
    </details>
  )
}

function AboutDetails({ about }: { about: ChatAbout }) {
  const rows = capabilities(about)
  return (
    <>
      {about.description && <p className="cp-about-desc">{about.description}</p>}
      {rows.length > 0 && (
        <dl className="cp-caps">
          {rows.map(([label, items]) => (
            <div key={label} className="cp-cap">
              <dt>{label}</dt>
              <dd>{items.map((item) => <span key={item} className="cp-chip">{item}</span>)}</dd>
            </div>
          ))}
        </dl>
      )}
      {about.answers_from_documents && <p className="cp-about-note">Answers from a set of documents.</p>}
      {about.pipeline_id && <PipelineInfo about={about} />}
    </>
  )
}

/** 👍 / 👎 under an answer; after a 👎, an optional note on what was wrong. */
function Rating({ message, onRate }: { message: Message; onRate: (rating: 1 | -1, comment?: string) => void }) {
  const [note, setNote] = useState('')
  const askNote = message.rating === -1 && !message.commented
  return (
    <div className="cp-rating">
      <button type="button" className={`cp-icon-btn${message.rating === 1 ? ' cp-icon-btn--on' : ''}`}
              aria-label="Good answer" aria-pressed={message.rating === 1} onClick={() => onRate(1)}>
        <ThumbsUp size={14} />
      </button>
      <button type="button" className={`cp-icon-btn${message.rating === -1 ? ' cp-icon-btn--on' : ''}`}
              aria-label="Bad answer" aria-pressed={message.rating === -1} onClick={() => onRate(-1)}>
        <ThumbsDown size={14} />
      </button>
      {askNote && (
        <form className="cp-rating-note" onSubmit={(e) => { e.preventDefault(); if (note.trim()) onRate(-1, note.trim()) }}>
          <input className="cp-rating-input" value={note} maxLength={4000} placeholder="What was wrong? (optional)"
                 aria-label="What was wrong" onChange={(e) => setNote(e.target.value)} />
          <button type="submit" className="cp-icon-btn" aria-label="Send note" disabled={!note.trim()}><ArrowUp size={14} /></button>
        </form>
      )}
      {message.rating && !askNote && <span className="cp-rating-thanks">Thanks for the feedback</span>}
    </div>
  )
}

const Avatar = ({ title, size = 'sm' }: { title: string; size?: 'sm' | 'lg' }) => (
  <span className={`cp-avatar cp-avatar--${size}`} aria-hidden="true">{(title.trim()[0] || 'A').toUpperCase()}</span>
)

export function ChatPage({ token }: { token: string }) {
  const [info, setInfo] = useState<ChatSession | null>(null)
  const [fatal, setFatal] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [showAbout, setShowAbout] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const begin = useCallback(async (previous: Saved | null) => {
    try {
      const s = await startSession(token, previous?.session ?? '')
      setInfo(s)
      document.title = s.title
      const kept = s.resumed && previous ? previous.messages : []
      setMessages(kept)
      save(token, { session: s.session, messages: kept })
      setFatal(null)
    } catch (e) {
      setFatal(e instanceof Error ? e.message : String(e))
    }
  }, [token])

  useEffect(() => { begin(load(token)) }, [begin, token])

  useEffect(() => {
    if (info) save(token, { session: info.session, messages })
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [messages, info, token])

  const updateLast = (fn: (m: Message) => Message) =>
    setMessages((ms) => [...ms.slice(0, -1), fn(ms[ms.length - 1])])

  const send = async (prompt?: string) => {
    const text = (prompt ?? input).trim()
    if (!text || busy || !info || text.length > info.max_message_chars) return
    if (prompt === undefined) setInput('')
    setShowAbout(false)
    setBusy(true)
    setMessages((ms) => [...ms, { role: 'user', content: text }, { role: 'assistant', content: '' }])
    const ctrl = new AbortController()
    abort.current = ctrl
    try {
      await sendMessage(token, info.session, text, (ev) => {
        if (ev.type === 'token') updateLast((m) => ({ ...m, content: m.content + ev.text }))
        else if (ev.type === 'done' && ev.feedback) updateLast((m) => ({ ...m, feedback: ev.feedback }))
        else if (ev.type === 'error')
          updateLast((m) => ({ ...m, content: ev.retract || !m.content ? ev.message : `${m.content}\n\n${ev.message}`, error: true }))
      }, ctrl.signal)
    } catch (e) {
      if (ctrl.signal.aborted) {
        updateLast((m) => ({ ...m, content: m.content || 'Stopped.' }))
      } else {
        const message = e instanceof Error ? e.message : String(e)
        updateLast((m) => ({ ...m, content: message, error: true }))
        if (e instanceof ChatError && e.status === 401) begin(null)   // session expired: start a fresh one
        if (e instanceof ChatError && e.status === 404) setFatal(message)
      }
    } finally {
      abort.current = null
      setBusy(false)
      inputRef.current?.focus()
    }
  }

  const rate = async (index: number, rating: 1 | -1, comment = '') => {
    const m = messages[index]
    if (!info || !m?.feedback) return
    const before = { rating: m.rating, commented: m.commented }
    setMessages((ms) => ms.map((x, j) => (j === index ? { ...x, rating, commented: x.commented || !!comment } : x)))
    try {
      await sendFeedback(token, info.session, m.feedback, rating, comment)
    } catch {
      setMessages((ms) => ms.map((x, j) => (j === index ? { ...x, ...before } : x)))   // not saved: show it unrated
    }
  }

  const newChat = () => {
    abort.current?.abort()
    setShowAbout(false)
    save(token, null)
    begin(null)
  }

  if (fatal) {
    return (
      <div className="cp-page">
        <div className="cp-shell">
          <div className="cp-center">
            <p className="cp-center-title">Chat unavailable</p>
            <p>{fatal}</p>
            <button type="button" className="cp-btn" onClick={() => begin(load(token))}>Try again</button>
          </div>
        </div>
      </div>
    )
  }

  if (!info) {
    return <div className="cp-page"><div className="cp-shell"><div className="cp-center">Loading…</div></div></div>
  }

  const tooLong = input.length > info.max_message_chars
  const about = info.about
  const empty = messages.length === 0
  const subtitle = about?.models[0] ? `AI assistant · ${about.models[0].replace(/ \(.*\)$/, '')}` : 'AI assistant'

  return (
    <div className="cp-page">
      <div className="cp-shell">
        <header className="cp-header">
          <Avatar title={info.title} />
          <div className="cp-heading">
            <h1 className="cp-title">{info.title}</h1>
            <p className="cp-subtitle">{subtitle}</p>
          </div>
          <div className="cp-header-actions">
            {about && !empty && (
              <button type="button" className={`cp-btn${showAbout ? ' cp-btn--on' : ''}`} aria-expanded={showAbout} aria-label="About"
                      onClick={() => setShowAbout((v) => !v)}>
                <Info size={15} aria-hidden="true" /><span className="cp-btn-label">About</span>
              </button>
            )}
            <button type="button" className="cp-btn" onClick={newChat} disabled={empty} aria-label="New chat">
              <Plus size={15} aria-hidden="true" /><span className="cp-btn-label">New chat</span>
            </button>
          </div>
        </header>

        {about && showAbout && !empty && (
          <div className="cp-about-panel"><AboutDetails about={about} /></div>
        )}

        <div className="cp-messages" ref={listRef}>
          {empty ? (
            <div className="cp-welcome">
              <Avatar title={info.title} size="lg" />
              <div className="cp-welcome-title">{info.greeting ? renderMarkdownBlock(info.greeting) : 'How can I help?'}</div>
              {about && <div className="cp-welcome-about"><AboutDetails about={about} /></div>}
              {info.starter_prompts.length > 0 && (
                <div className="cp-starters" aria-label="Example questions">
                  {info.starter_prompts.map((p) => (
                    <button key={p} type="button" className="cp-starter" onClick={() => send(p)}>{p}</button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <>
              {info.greeting && (
                <div className="cp-row cp-row--assistant">
                  <Avatar title={info.title} />
                  <div className="cp-msg cp-msg--assistant">{renderMarkdownBlock(info.greeting)}</div>
                </div>
              )}
              {messages.map((m, i) => m.role === 'user' ? (
                <div key={i} className="cp-row cp-row--user"><div className="cp-msg cp-msg--user">{m.content}</div></div>
              ) : (
                <div key={i} className="cp-row cp-row--assistant">
                  <Avatar title={info.title} />
                  <div className="cp-msg-col">
                    <div className={`cp-msg cp-msg--assistant${m.error ? ' cp-msg--error' : ''}`}>
                      {m.content
                        ? renderAnswer(m.content)
                        : <span className="cp-typing" aria-label="Typing"><i /><i /><i /></span>}
                    </div>
                    {m.feedback && !m.error && (
                      <Rating message={m} onRate={(rating, comment) => rate(i, rating, comment)} />
                    )}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>

        <div className="cp-composer-wrap">
          <form className={`cp-composer${tooLong ? ' cp-composer--invalid' : ''}`}
                onSubmit={(e) => { e.preventDefault(); send() }}>
            <textarea
              ref={inputRef}
              className="cp-input"
              value={input}
              rows={1}
              placeholder={`Message ${info.title}`}
              aria-label="Message"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() }
              }}
            />
            {busy ? (
              <button type="button" className="cp-send cp-send--stop" aria-label="Stop" onClick={() => abort.current?.abort()}>
                <Square size={14} fill="currentColor" aria-hidden="true" />
              </button>
            ) : (
              <button type="submit" className="cp-send" aria-label="Send" disabled={!input.trim() || tooLong}>
                <ArrowUp size={18} aria-hidden="true" />
              </button>
            )}
          </form>
          <p className={`cp-footer${tooLong ? ' cp-footer--warn' : ''}`}>
            {tooLong
              ? `Messages can be up to ${info.max_message_chars} characters.`
              : 'Answers are generated by AI and may be wrong.'}
          </p>
        </div>
      </div>
    </div>
  )
}
