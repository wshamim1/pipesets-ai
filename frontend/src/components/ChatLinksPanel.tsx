import { useCallback, useEffect, useMemo, useState } from 'react'
import qrcode from 'qrcode-generator'
import { API_BASE } from '../types'
import type { AppRecord } from '../types'
import { useCredentials } from '../context/CredentialsContext'
import { browserProviderKeys } from '../utils/providerKeys'
import { bubbleSnippet, iframeSnippet, samplePage } from '../utils/chatEmbed'
import { saveBlob } from '../utils/download'

interface ChatLink {
  id: string
  app_id: string
  name: string
  title: string
  greeting: string
  access: 'public'
  token_prefix: string
  token?: string
  rate_limit_per_min: number
  max_turns: number
  max_message_chars: number
  daily_message_cap: number
  show_details: boolean
  starter_prompts: string[]
  message_count: number
  last_used_at: string | null
  created_at: string
  revoked_at: string | null
  active: boolean
}

type LimitKey = 'rate_limit_per_min' | 'max_turns' | 'max_message_chars' | 'daily_message_cap'

interface FormState extends Record<LimitKey, string> {
  title: string
  greeting: string
  show_details: boolean
  starter_prompts: string   // one per line
}

const MAX_STARTERS = 6

const LIMIT_FIELDS: { key: LimitKey; label: string; hint: string }[] = [
  { key: 'rate_limit_per_min', label: 'Messages per minute, per visitor', hint: '0 = unlimited' },
  { key: 'max_turns', label: 'Messages per conversation', hint: '0 = unlimited' },
  { key: 'daily_message_cap', label: 'Messages per day, all visitors', hint: '0 = unlimited' },
  { key: 'max_message_chars', label: 'Longest message (characters)', hint: '' },
]

// Behind the edge proxy the chat page is served on the public host, like /v1 (deploy/edge)
const linkBase = import.meta.env.VITE_PUBLIC_API_URL || window.location.origin
const chatLinkUrl = (token: string) => `${linkBase}/c/${token}`
const isLocal = (url: string) => /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(url)

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

async function errorText(r: Response): Promise<string> {
  const d = await r.json().catch(() => ({}))
  return typeof d.detail === 'string' ? d.detail : r.statusText
}

function QrCode({ text }: { text: string }) {
  const { size, path } = useMemo(() => {
    const qr = qrcode(0, 'M')
    qr.addData(text)
    qr.make()
    const n = qr.getModuleCount()
    let d = ''
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += `M${c + 2},${r + 2}h1v1h-1z`
    return { size: n + 4, path: d }
  }, [text])
  return (
    <svg className="chatlink-qr" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="QR code for the chat link"
         shapeRendering="crispEdges">
      <rect width={size} height={size} fill="#fff" />
      <path d={path} fill="#000" />
    </svg>
  )
}

const promptLines = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean)

type EmbedKind = 'bubble' | 'inline'

const EMBED_KINDS: { id: EmbedKind; label: string; hint: string }[] = [
  { id: 'bubble', label: 'Chat button', hint: 'A round button in the bottom-right corner opens the chat. Paste before </body>.' },
  { id: 'inline', label: 'Inline', hint: 'The chat in a box on the page. Paste where it should appear.' },
]

/** Copy-paste HTML for putting the chat on a website, and a sample page to try it. */
function EmbedSection({ url, title }: { url: string; title: string }) {
  const [kind, setKind] = useState<EmbedKind>('bubble')
  const [copied, setCopied] = useState(false)
  const code = kind === 'bubble' ? bubbleSnippet(url, title) : iframeSnippet(url, title)
  const copy = () => navigator.clipboard.writeText(code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })
  const download = () => saveBlob(new Blob([samplePage(url, title)], { type: 'text/html' }), 'chat-embed-example.html')

  return (
    <div className="chatlink-embed">
      <div className="chatlink-embed-tabs" role="tablist" aria-label="Embed type">
        {EMBED_KINDS.map((k) => (
          <button key={k.id} type="button" role="tab" aria-selected={kind === k.id}
                  className={`chatlink-embed-tab${kind === k.id ? ' chatlink-embed-tab--on' : ''}`}
                  onClick={() => setKind(k.id)}>
            {k.label}
          </button>
        ))}
      </div>
      <p className="sched-muted">{EMBED_KINDS.find((k) => k.id === kind)!.hint}</p>
      <pre className="sched-output chatlink-embed-code">{code}</pre>
      <div className="chatlink-gen-row">
        <button type="button" className="docs-btn docs-btn--primary" onClick={copy}>{copied ? 'Copied' : 'Copy code'}</button>
        <button type="button" className="docs-btn" onClick={download}>Download sample page</button>
      </div>
      <p className="sched-muted">
        The sample page has both, with this link filled in — open it in a browser to try them. Any website can
        embed the link, the same as anyone can open it; turning the link off stops it everywhere.
      </p>
    </div>
  )
}

function LinkForm({ app, initial, onCancel, onSave }: {
  app: AppRecord
  initial: FormState
  onCancel: () => void
  onSave: (body: Record<string, unknown>) => Promise<boolean>
}) {
  const [f, setF] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError] = useState<string | null>(null)
  const { resolveApiKey } = useCredentials()
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }))
  const prompts = promptLines(f.starter_prompts)

  // Same generator as the Run panel's starter prompts (backend routers/eval.py)
  const generate = async () => {
    setGenerating(true)
    setGenError(null)
    try {
      const r = await fetch(`${API_BASE}/api/eval/suggest-prompts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          flow_data: app.flow_data, app_id: app.id, app_name: app.name, count: 4,
          provider_keys: browserProviderKeys(resolveApiKey),
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setGenError(typeof d.detail === 'string' ? d.detail : r.statusText); return }
      const generated: string[] = d.prompts ?? []
      if (generated.length === 0) { setGenError('The model returned no prompts.'); return }
      set('starter_prompts', [...prompts, ...generated].slice(0, MAX_STARTERS).join('\n'))
    } catch (e) {
      setGenError(e instanceof Error ? e.message : String(e))
    } finally {
      setGenerating(false)
    }
  }

  const submit = async () => {
    setSaving(true)
    const body: Record<string, unknown> = {
      title: f.title.trim(), greeting: f.greeting.trim(),
      show_details: f.show_details, starter_prompts: prompts.slice(0, MAX_STARTERS),
    }
    for (const { key } of LIMIT_FIELDS) {
      const n = parseInt(f[key], 10)
      if (!Number.isNaN(n)) body[key] = Math.max(key === 'max_message_chars' ? 1 : 0, n)
    }
    const ok = await onSave(body)
    setSaving(false)
    if (ok) onCancel()
  }

  return (
    <div className="sched-form">
      <label className="sched-field">
        <span>Title</span>
        <input value={f.title} maxLength={200} placeholder="Defaults to the pipeline's name"
               onChange={(e) => set('title', e.target.value)} />
      </label>
      <label className="sched-field">
        <span>Greeting</span>
        <textarea value={f.greeting} maxLength={2000} rows={2} placeholder="Hi! How can I help?"
                  onChange={(e) => set('greeting', e.target.value)} />
      </label>
      <div className="sched-field">
        <span>
          Sample prompts <span className="sched-muted">· one per line, up to {MAX_STARTERS}; visitors tap one to start</span>
        </span>
        <textarea value={f.starter_prompts} rows={4} aria-label="Sample prompts"
                  placeholder={'What can you help me with?\nWhat is the weather in Tokyo?'}
                  onChange={(e) => set('starter_prompts', e.target.value)} />
        <div className="chatlink-gen-row">
          <button type="button" className="docs-btn" disabled={generating || prompts.length >= MAX_STARTERS}
                  onClick={generate}>
            {generating ? 'Generating…' : '✨ Generate from pipeline'}
          </button>
          {prompts.length > MAX_STARTERS && <span className="sched-muted">Only the first {MAX_STARTERS} are kept.</span>}
        </div>
        {genError && <div className="sched-error sched-error--inline">{genError}</div>}
      </div>
      <label className="chatlink-check">
        <input type="checkbox" checked={f.show_details} onChange={(e) => set('show_details', e.target.checked)} />
        <span>
          Show pipeline details on the chat page
          <span className="sched-muted"> — description and the names of its models, tools, MCP servers and agents.
            Never prompts, connections or keys.</span>
        </span>
      </label>
      {LIMIT_FIELDS.map(({ key, label, hint }) => (
        <label key={key} className="sched-field">
          <span>{label}{hint && <span className="sched-muted"> · {hint}</span>}</span>
          <input type="number" min={key === 'max_message_chars' ? 1 : 0} value={f[key]}
                 onChange={(e) => set(key, e.target.value)} />
        </label>
      ))}
      <div className="sched-form-actions">
        <button type="button" className="docs-btn" onClick={onCancel}>Cancel</button>
        <button type="button" className="docs-btn docs-btn--primary" disabled={saving} onClick={submit}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  )
}

const toForm = (l?: ChatLink): FormState => ({
  title: l?.title ?? '',
  greeting: l?.greeting ?? '',
  rate_limit_per_min: String(l?.rate_limit_per_min ?? 10),
  max_turns: String(l?.max_turns ?? 50),
  max_message_chars: String(l?.max_message_chars ?? 4000),
  daily_message_cap: String(l?.daily_message_cap ?? 500),
  show_details: l?.show_details ?? true,
  starter_prompts: (l?.starter_prompts ?? []).join('\n'),
})

/** Public chat links for the open pipeline (Build toolbar → Chat link). */
export function ChatLinksPanel({ app }: { app: AppRecord | null }) {
  const [links, setLinks] = useState<ChatLink[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<{ editing: ChatLink | null } | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [showRevoked, setShowRevoked] = useState(false)
  const [embedFor, setEmbedFor] = useState<string | null>(null)

  const appId = app?.id ?? ''
  const blocked = !app
    ? 'Save and publish this pipeline to share a chat link.'
    : !(app.version ?? 0)
      ? 'Publish this pipeline to share a chat link — visitors always chat with the latest published version.'
      : app.status !== 'published'
        ? 'This pipeline is being edited, so its chat links answer "unavailable" until you publish it again.'
        : null

  const load = useCallback(() => {
    if (!appId) { setLinks([]); return }
    setLoading(true)
    fetch(`${API_BASE}/api/chat-links?app_id=${encodeURIComponent(appId)}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error(await errorText(r)))))
      .then((d: ChatLink[]) => { setLinks(d); setError(null) })
      .catch((e) => setError(`Failed to load chat links: ${e.message}`))
      .finally(() => setLoading(false))
  }, [appId])

  useEffect(() => { load(); setForm(null) }, [load])

  const call = async (url: string, init: RequestInit): Promise<boolean> => {
    try {
      const r = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json' } })
      if (!r.ok) { setError(await errorText(r)); return false }
      setError(null)
      load()
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return false
    }
  }

  const save = (body: Record<string, unknown>) => form?.editing
    ? call(`${API_BASE}/api/chat-links/${encodeURIComponent(form.editing.id)}`, { method: 'PATCH', body: JSON.stringify(body) })
    : call(`${API_BASE}/api/chat-links`, { method: 'POST', body: JSON.stringify({ ...body, app_id: appId }) })

  // One click with the server's default limits; Edit changes them afterwards
  const createDefault = () => call(`${API_BASE}/api/chat-links`, { method: 'POST', body: JSON.stringify({ app_id: appId }) })

  const rotate = (l: ChatLink) => {
    if (!window.confirm(`Give "${l.title || l.name}" a new URL? The current URL (and any QR code or embed using it) stops working at once; settings and conversations stay.`)) return
    call(`${API_BASE}/api/chat-links/${encodeURIComponent(l.id)}/rotate`, { method: 'POST' })
  }

  const revoke = (l: ChatLink) => {
    if (!window.confirm(`Turn off "${l.name}"? Anyone using it is cut off on their next message. This can't be undone.`)) return
    call(`${API_BASE}/api/chat-links/${encodeURIComponent(l.id)}`, { method: 'DELETE' })
  }

  const copy = (id: string, text: string) =>
    navigator.clipboard.writeText(text).then(() => { setCopied(id); setTimeout(() => setCopied(null), 1500) })

  const active = links.filter((l) => l.active)
  const revoked = links.filter((l) => !l.active)

  // One link is the usual case; a list (and its count) only shows once there's a second one
  return (
    <div className="sched-panel sched-panel--compact">
      <div className="sched-toolbar">
        <div className="ops-toolbar-left">
          {active.length > 1 && <span className="ops-count-badge">{active.length} chat links</span>}
        </div>
        <div className="ops-toolbar-right">
          <button type="button" className="ops-refresh-btn" onClick={load} disabled={loading || !!blocked}>
            {loading ? '…' : '↻'}
          </button>
        </div>
      </div>

      <div className="sched-body">
        {blocked && <div className="sched-empty">{blocked}</div>}
        {error && <div className="sched-error">{error}</div>}
        {!blocked && isLocal(linkBase) && (
          <div className="sched-note">
            Chat links point at <code>localhost</code>, so they only open on this computer. To open one on a phone,
            use Settings → Share via ngrok and open the builder through that address, or deploy the server.
          </div>
        )}
        {form && app && (
          <LinkForm app={app} initial={toForm(form.editing ?? undefined)} onCancel={() => setForm(null)} onSave={save} />
        )}

        {!blocked && !form && active.length === 0 && !loading && (
          <div className="sched-empty">
            <p className="sched-empty-title">No chat links yet</p>
            <p className="sched-muted">
              Get a link anyone can open on a phone or laptop to chat with this pipeline — no account needed. Each
              visitor gets their own conversation, and you can turn a link off at any time.
            </p>
            <button type="button" className="docs-btn docs-btn--primary" onClick={createDefault}>Create chat link</button>
          </div>
        )}

        {active.map((l) => {
          const url = l.token ? chatLinkUrl(l.token) : ''
          return (
            <div key={l.id} className="sched-card sched-card--active">
              <div className="sched-card-head">
                <div className="sched-card-title">
                  <span className="sched-card-name">{l.title || l.name}</span>
                  <span className="sched-pill sched-pill--active">anyone with the link</span>
                </div>
                <div className="hook-copy-row">
                  <code className="hook-url">{url}</code>
                  <button type="button" className="docs-btn" onClick={() => copy(l.id, url)}>
                    {copied === l.id ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <div className="chatlink-share">
                  <QrCode text={url} />
                  <div className="sched-muted">
                    Scan to open on a phone.<br />
                    {l.message_count} message{l.message_count !== 1 ? 's' : ''}
                    {l.last_used_at ? ` · last ${when(l.last_used_at)}` : ' · not used yet'}<br />
                    Limits: {l.rate_limit_per_min || '∞'}/min per visitor · {l.max_turns || '∞'} per conversation ·{' '}
                    {l.daily_message_cap || '∞'}/day<br />
                    {l.show_details ? 'Shows pipeline details' : 'Hides pipeline details'} ·{' '}
                    {l.starter_prompts.length
                      ? `${l.starter_prompts.length} sample prompt${l.starter_prompts.length !== 1 ? 's' : ''}`
                      : 'no sample prompts — Edit to add some'}
                  </div>
                </div>
              </div>
              <div className="sched-actions">
                <a className="docs-btn" href={url} target="_blank" rel="noreferrer">Open</a>
                <button type="button" className="docs-btn" aria-expanded={embedFor === l.id}
                        onClick={() => setEmbedFor(embedFor === l.id ? null : l.id)}>
                  {embedFor === l.id ? 'Hide embed code' : 'Embed on a website'}
                </button>
                <button type="button" className="docs-btn" disabled={!!form} onClick={() => setForm({ editing: l })}>
                  Edit
                </button>
                <button type="button" className="docs-btn" title="Replace the URL, e.g. if it was shared too widely"
                        onClick={() => rotate(l)}>
                  New URL
                </button>
                <button type="button" className="docs-btn sched-delete" onClick={() => revoke(l)}>Turn off</button>
              </div>
              {embedFor === l.id && url && <EmbedSection url={url} title={l.title || app?.name || l.name} />}
            </div>
          )
        })}

        {!blocked && !form && active.length > 0 && (
          <button type="button" className="chatlink-add-another" onClick={() => setForm({ editing: null })}>
            + Add another link — with its own limits, greeting or audience
          </button>
        )}

        {revoked.length > 0 && (
          <button type="button" className="docs-btn" onClick={() => setShowRevoked((v) => !v)}>
            {showRevoked ? 'Hide' : 'Show'} {revoked.length} turned-off link{revoked.length !== 1 ? 's' : ''}
          </button>
        )}
        {showRevoked && revoked.map((l) => (
          <div key={l.id} className="sched-card sched-card--paused">
            <div className="sched-card-head">
              <div className="sched-card-title">
                <span className="sched-card-name">{l.title || l.name}</span>
                <span className="sched-pill">off</span>
              </div>
              <div className="sched-muted">
                <code>/c/{l.token_prefix}…</code> · {l.message_count} messages
                {l.revoked_at ? ` · turned off ${when(l.revoked_at)}` : ''}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Build toolbar → Chat link: the same panel in a dialog. */
export function ChatLinksModal({ app, onClose }: { app: AppRecord; onClose: () => void }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="export-modal chatlink-modal" role="dialog" aria-label="Chat link" onClick={(e) => e.stopPropagation()}>
        <div className="export-modal-header">
          <div>
            <h2 className="export-modal-title">Chat link</h2>
            <p className="export-modal-subtitle">
              Anyone with the link can chat with “{app.name}” on a phone or laptop — no account needed.
            </p>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="export-modal-body">
          <ChatLinksPanel app={app} />
        </div>
      </div>
    </div>
  )
}
