import { useCallback, useEffect, useState } from 'react'
import { API_BASE, PUBLIC_API_BASE } from '../types'
import { RETRY_NOTE, RetriesSelect, attemptLabel, retriesField } from './RetriesSelect'
import { HelpLink } from './docs/HelpLink'

interface PipelineRef {
  id: string
  name: string
  status?: 'draft' | 'published'
  version?: number
}

interface Webhook {
  id: string
  app_id: string
  app_name: string | null
  app_version: number
  name: string
  token_prefix: string
  prompt_template: string
  has_secret: boolean
  enabled: boolean
  running: number
  timeout_ms: number
  retries: number
  last_triggered_at: string | null
  last_status: string | null
  last_error: string | null
}

interface WebhookRun {
  id: string
  trigger: 'webhook' | 'manual'
  status: 'queued' | 'running' | 'retrying' | 'completed' | 'failed' | 'paused' | 'interrupted'
  attempts: number
  app_version: number
  run_id: string | null
  payload_preview: string | null
  output_preview: string | null
  error: string | null
  latency_ms: number
  started_at: string
}

interface Props {
  /** Pipelines to choose from (Monitor). Ignored when `fixedApp` is set. */
  apps: PipelineRef[]
  /** Build sidebar: show and create webhooks for this pipeline only. */
  fixedApp?: PipelineRef | null
  compact?: boolean
}

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

async function errorText(r: Response): Promise<string> {
  const d = await r.json().catch(() => ({}))
  return typeof d.detail === 'string' ? d.detail : r.statusText
}

function randomSecret(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(24))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

const hookUrl = (token: string) => `${PUBLIC_API_BASE}/v1/hooks/${token}`

// ── Token reveal (shown once after create / rotate) ──────────────────────────

function TokenReveal({ token, secret, onDone }: { token: string; secret: string | null; onDone: () => void }) {
  const [copied, setCopied] = useState<string | null>(null)
  const copy = (label: string, text: string) =>
    navigator.clipboard.writeText(text).then(() => { setCopied(label); setTimeout(() => setCopied(null), 1500) })
  const curl = `curl -X POST ${hookUrl(token)} \\\n  -H 'Content-Type: application/json' \\\n  -d '{"text": "hello"}'`

  return (
    <div className="sched-note hook-reveal">
      <p><strong>Copy this URL now</strong> — it won't be shown again. Anyone with it can start this pipeline.</p>
      <div className="hook-copy-row">
        <code className="hook-url">{hookUrl(token)}</code>
        <button type="button" className="docs-btn" onClick={() => copy('url', hookUrl(token))}>
          {copied === 'url' ? 'Copied' : 'Copy'}
        </button>
      </div>
      {secret && (
        <>
          <p>Signing secret — send <code>X-Hub-Signature-256: sha256=HMAC(secret, body)</code> with each call:</p>
          <div className="hook-copy-row">
            <code className="hook-url">{secret}</code>
            <button type="button" className="docs-btn" onClick={() => copy('secret', secret)}>
              {copied === 'secret' ? 'Copied' : 'Copy'}
            </button>
          </div>
        </>
      )}
      {!secret && <pre className="sched-output">{curl}</pre>}
      <div className="sched-form-actions">
        <button type="button" className="docs-btn docs-btn--primary" onClick={onDone}>I've saved it</button>
      </div>
    </div>
  )
}

// ── Form ─────────────────────────────────────────────────────────────────────

interface FormState {
  app_id: string
  name: string
  prompt_template: string
  timeout_s: string
  retries: string
  secret: string            // new secret to set ('' = leave as is when editing)
  remove_secret: boolean
}

function WebhookForm({ initial, editing, pipelines, fixed, onCancel, onSaved }: {
  initial: FormState
  editing: Webhook | null
  pipelines: PipelineRef[]
  fixed: boolean
  onCancel: () => void
  onSaved: (created: { token: string; secret: string | null } | null) => void
}) {
  const [f, setF] = useState<FormState>(initial)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }))

  const save = async () => {
    if (!f.app_id) { setError('Pick a pipeline.'); return }
    if (!f.prompt_template.trim()) { setError('Enter a prompt template.'); return }
    setSaving(true)
    setError(null)
    const body: Record<string, unknown> = {
      name: f.name, prompt_template: f.prompt_template,
      timeout_ms: Math.max(1, parseInt(f.timeout_s, 10) || 120) * 1000,
      retries: retriesField(f.retries),
    }
    if (f.remove_secret) body.secret = ''
    else if (f.secret) body.secret = f.secret
    try {
      const r = editing
        ? await fetch(`${API_BASE}/api/webhooks/${encodeURIComponent(editing.id)}`, {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
          })
        : await fetch(`${API_BASE}/api/webhooks`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...body, app_id: f.app_id }),
          })
      if (!r.ok) { setError(await errorText(r)); return }
      const d = await r.json()
      onSaved(editing ? null : { token: d.token, secret: f.secret || null })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const publishable = pipelines.filter((p) => (p.version ?? 0) > 0)

  return (
    <div className="sched-form">
      {!fixed && !editing && (
        <label className="sched-field">
          <span>Pipeline</span>
          <select className="ops-select" value={f.app_id} onChange={(e) => set('app_id', e.target.value)}>
            <option value="">Select a published pipeline…</option>
            {publishable.map((p) => <option key={p.id} value={p.id}>{p.name} (v{p.version})</option>)}
          </select>
        </label>
      )}

      <label className="sched-field">
        <span>Name</span>
        <input className="sched-input" value={f.name} placeholder="e.g. GitHub issue triage"
               onChange={(e) => set('name', e.target.value)} />
      </label>

      <label className="sched-field">
        <span>Prompt<HelpLink page="09-monitor-automate" section="webhooks" label="Prompt template syntax" /></span>
        <textarea className="sched-input sched-textarea sched-input--mono" rows={3} value={f.prompt_template}
                  onChange={(e) => set('prompt_template', e.target.value)} />
      </label>
      <p className="sched-muted">
        Filled from each call: <code>{'{{body}}'}</code> is the whole payload, <code>{'{{body.issue.title}}'}</code> a
        field, <code>{'{{body.items.0.name}}'}</code> a list item, <code>{'{{query.repo}}'}</code> a URL parameter.
      </p>

      <details className="sched-advanced" open={!!editing?.has_secret}>
        <summary>Security &amp; limits</summary>
        <div className="sched-field">
          <span>Signing secret</span>
          {editing?.has_secret && !f.secret && !f.remove_secret ? (
            <div className="sched-cadence">
              <span className="sched-muted">Calls must be signed.</span>
              <button type="button" className="docs-btn" onClick={() => set('secret', randomSecret())}>Replace</button>
              <button type="button" className="docs-btn" onClick={() => set('remove_secret', true)}>Remove</button>
            </div>
          ) : (
            <div className="sched-cadence">
              <input className="sched-input sched-input--mono" value={f.secret}
                     placeholder={f.remove_secret ? 'Signing will be turned off' : 'Optional — unsigned calls are accepted'}
                     onChange={(e) => { set('secret', e.target.value); set('remove_secret', false) }} />
              <button type="button" className="docs-btn"
                      onClick={() => { set('secret', randomSecret()); set('remove_secret', false) }}>Generate</button>
            </div>
          )}
        </div>
        <p className="sched-muted">
          With a secret, each call needs <code>X-Hub-Signature-256</code> (GitHub sends this when you give it the same
          secret) or <code>X-Pipesets-Signature</code>: <code>sha256=</code> + hex HMAC-SHA256 of the raw body.
        </p>
        <div className="sched-advanced-row">
          <label className="sched-inline">
            Timeout
            <input className="sched-input sched-input--num" type="number" min={1} max={600} value={f.timeout_s}
                   onChange={(e) => set('timeout_s', e.target.value)} />
            s
          </label>
          <RetriesSelect value={f.retries} onChange={(v) => set('retries', v)} allowDefault={!editing} />
        </div>
        <p className="sched-muted">{RETRY_NOTE}</p>
        <p className="sched-muted">
          Webhook runs use API keys set on the pipeline's nodes or the server's environment — keys saved only in this
          browser aren't available to them.
        </p>
      </details>

      {error && <div className="sched-error">{error}</div>}

      <div className="sched-form-actions">
        <button type="button" className="docs-btn" onClick={onCancel} disabled={saving}>Cancel</button>
        <button type="button" className="docs-btn docs-btn--primary" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : editing ? 'Save changes' : 'Create webhook'}
        </button>
      </div>
    </div>
  )
}

// ── Test call ────────────────────────────────────────────────────────────────

function TestCall({ hook, onStarted }: { hook: Webhook; onStarted: () => void }) {
  const [body, setBody] = useState('{\n  "text": "hello"\n}')
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const send = async () => {
    let parsed: unknown
    try { parsed = body.trim() ? JSON.parse(body) : {} } catch { parsed = body }
    try {
      const r = await fetch(`${API_BASE}/api/webhooks/${encodeURIComponent(hook.id)}/test`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body: parsed }),
      })
      if (!r.ok) { setError(await errorText(r)); setResult(null); return }
      setResult((await r.json()).prompt)
      setError(null)
      onStarted()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="sched-form">
      <label className="sched-field">
        <span>Sample payload</span>
        <textarea className="sched-input sched-textarea sched-input--mono" rows={4} value={body}
                  onChange={(e) => setBody(e.target.value)} />
      </label>
      {error && <div className="sched-error">{error}</div>}
      {result && <div className="sched-muted">Started with prompt: <pre className="sched-output">{result}</pre></div>}
      <div className="sched-form-actions">
        <button type="button" className="docs-btn docs-btn--primary" onClick={send}>▶ Send test</button>
      </div>
    </div>
  )
}

// ── Run history ──────────────────────────────────────────────────────────────

function RunHistory({ webhookId, refreshKey, retries }: { webhookId: string; refreshKey: number; retries: number }) {
  const [runs, setRuns] = useState<WebhookRun[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/webhooks/${encodeURIComponent(webhookId)}/runs?limit=20`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setRuns)
      .catch(() => setRuns([]))
  }, [webhookId, refreshKey])

  if (runs === null) return <div className="sched-runs sched-muted">Loading…</div>
  if (runs.length === 0) return <div className="sched-runs sched-muted">No calls yet.</div>

  return (
    <div className="sched-runs">
      {runs.map((r) => (
        <div key={r.id} className="sched-run">
          <button type="button" className="sched-run-row" onClick={() => setOpen(open === r.id ? null : r.id)}>
            <span className={`sched-dot sched-dot--${r.status}`} title={r.status} />
            <span className="sched-run-status">{r.status}</span>
            <span className="sched-muted">{r.trigger === 'manual' ? 'test' : 'webhook'}{r.app_version ? ` · v${r.app_version}` : ''}</span>
            <span className="sched-run-time">{when(r.started_at)}</span>
            {attemptLabel(r.attempts, retries) && <span className="sched-muted">{attemptLabel(r.attempts, retries)}</span>}
            {r.latency_ms > 0 && <span className="sched-muted">{(r.latency_ms / 1000).toFixed(1)}s</span>}
          </button>
          {open === r.id && (
            <div className="sched-run-detail">
              {r.payload_preview && <><div className="sched-muted">Payload</div><pre className="sched-output">{r.payload_preview}</pre></>}
              {r.error && <div className="sched-error">{r.error}</div>}
              {r.output_preview && <><div className="sched-muted">Output</div><pre className="sched-output">{r.output_preview}</pre></>}
              {r.run_id && <div className="sched-muted">Trace run id: <code>{r.run_id}</code></div>}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Panel ────────────────────────────────────────────────────────────────────

/** Webhook triggers for published pipelines: list, create, test, rotate URL, history. */
export function WebhooksPanel({ apps, fixedApp, compact }: Props) {
  const [hooks, setHooks] = useState<Webhook[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<{ initial: FormState; editing: Webhook | null } | null>(null)
  const [reveal, setReveal] = useState<{ token: string; secret: string | null } | null>(null)
  const [expanded, setExpanded] = useState<{ id: string; view: 'history' | 'test' } | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const fixed = fixedApp !== undefined
  const appId = fixedApp?.id ?? ''

  const load = useCallback(() => {
    if (fixed && !appId) { setHooks([]); return }
    setLoading(true)
    const qs = appId ? `?app_id=${encodeURIComponent(appId)}` : ''
    fetch(`${API_BASE}/api/webhooks${qs}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error(await errorText(r)))))
      .then((d: Webhook[]) => { setHooks(d); setError(null) })
      .catch((e) => setError(`Failed to load webhooks: ${e.message}`))
      .finally(() => { setLoading(false); setRefreshKey((k) => k + 1) })
  }, [fixed, appId])

  useEffect(() => { load(); setForm(null); setExpanded(null); setReveal(null) }, [load])

  const anyRunning = hooks.some((h) => h.running > 0)
  useEffect(() => {
    if (!anyRunning) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [anyRunning, load])

  const act = async (url: string, init: RequestInit) => {
    try {
      const r = await fetch(url, init)
      if (!r.ok) { setError(await errorText(r)); return null }
      setError(null)
      load()
      return r.json()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return null
    }
  }

  const toggle = (h: Webhook) =>
    act(`${API_BASE}/api/webhooks/${encodeURIComponent(h.id)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: !h.enabled }),
    })

  const rotate = async (h: Webhook) => {
    if (!window.confirm(`Issue a new URL for "${h.name}"? The current URL stops working immediately.`)) return
    const d = await act(`${API_BASE}/api/webhooks/${encodeURIComponent(h.id)}/rotate`, { method: 'POST' })
    if (d) setReveal({ token: d.token, secret: null })
  }

  const remove = (h: Webhook) => {
    if (!window.confirm(`Delete "${h.name}" and its call history? Its URL stops working.`)) return
    act(`${API_BASE}/api/webhooks/${encodeURIComponent(h.id)}`, { method: 'DELETE' })
  }

  const newForm = (): FormState => ({
    app_id: appId, name: '', prompt_template: '{{body}}', timeout_s: '120', retries: '', secret: '', remove_secret: false,
  })
  const editForm = (h: Webhook): FormState => ({
    app_id: h.app_id, name: h.name, prompt_template: h.prompt_template,
    timeout_s: String(Math.round(h.timeout_ms / 1000)), retries: String(h.retries), secret: '', remove_secret: false,
  })

  const blocked = fixed && (!fixedApp
    ? 'Save and publish this pipeline to add a webhook.'
    : !(fixedApp.version ?? 0)
      ? 'Publish this pipeline to add a webhook — calls always run the latest published version.'
      : null)

  return (
    <div className={`sched-panel${compact ? ' sched-panel--compact' : ' ops-panel'}`}>
      <div className={compact ? 'sched-toolbar' : 'ops-toolbar'}>
        <div className="ops-toolbar-left">
          {!compact && <span className="ops-panel-title">Webhooks</span>}
          <span className="ops-count-badge">{hooks.length} webhook{hooks.length !== 1 ? 's' : ''}</span>
        </div>
        <div className="ops-toolbar-right">
          <button type="button" className="ops-refresh-btn" onClick={load} disabled={loading || !!blocked}>
            {loading ? '…' : '↻'}
          </button>
          <button type="button" className="docs-btn docs-btn--primary" disabled={!!blocked || !!form || !!reveal}
                  onClick={() => setForm({ initial: newForm(), editing: null })}>
            + New webhook
          </button>
        </div>
      </div>

      <div className="sched-body">
        {blocked && <div className="sched-empty">{blocked}</div>}
        {error && <div className="sched-error">{error}</div>}
        {reveal && <TokenReveal token={reveal.token} secret={reveal.secret} onDone={() => setReveal(null)} />}

        {form && (
          <WebhookForm
            key={form.editing?.id ?? 'new'}
            initial={form.initial}
            editing={form.editing}
            pipelines={apps}
            fixed={fixed}
            onCancel={() => setForm(null)}
            onSaved={(created) => { setForm(null); if (created) setReveal(created); load() }}
          />
        )}

        {!blocked && !form && !reveal && hooks.length === 0 && !loading && (
          <div className="sched-empty">
            <p className="sched-empty-title">No webhooks yet</p>
            <p className="sched-muted">
              Give a published pipeline a URL that other systems can call — a GitHub issue, a form submission, a
              monitoring alert. The request body fills the prompt, and each call is recorded with its output.
            </p>
          </div>
        )}

        {hooks.map((h) => {
          const state = h.running > 0 ? 'running' : h.enabled ? 'active' : 'paused'
          const view = expanded?.id === h.id ? expanded.view : null
          return (
            <div key={h.id} className={`sched-card sched-card--${state}`}>
              <div className="sched-card-head">
                <div className="sched-card-title">
                  <span className="sched-card-name">{h.name}</span>
                  <span className={`sched-pill sched-pill--${state}`}>{state === 'paused' ? 'disabled' : state}</span>
                  {h.has_secret && <span className="sched-pill" title="Calls must be signed">signed</span>}
                </div>
                {!fixed && (
                  <div className="sched-muted">
                    {h.app_name ?? 'Deleted pipeline'}{h.app_version ? ` · v${h.app_version}` : ''}
                  </div>
                )}
                <div className="sched-card-cadence">
                  <code className="sched-cron">POST /v1/hooks/{h.token_prefix}…</code>
                </div>
                <div className="sched-card-meta">
                  {h.last_triggered_at ? (
                    <span title={when(h.last_triggered_at)}>
                      Last call {when(h.last_triggered_at)}
                      {h.last_status && <span className={`sched-dot sched-dot--${h.last_status}`} title={h.last_status} />}
                    </span>
                  ) : <span className="sched-muted">Never called</span>}
                </div>
                {h.last_error && <div className="sched-error sched-error--inline">{h.last_error}</div>}
                <div className="sched-prompt" title={h.prompt_template}>“{h.prompt_template}”</div>
              </div>

              <div className="sched-actions">
                <button type="button" className="docs-btn"
                        onClick={() => setExpanded(view === 'test' ? null : { id: h.id, view: 'test' })}>
                  {view === 'test' ? 'Close test' : '▶ Test'}
                </button>
                <button type="button" className="docs-btn" onClick={() => toggle(h)}>
                  {h.enabled ? 'Disable' : 'Enable'}
                </button>
                <button type="button" className="docs-btn" disabled={!!form}
                        onClick={() => setForm({ initial: editForm(h), editing: h })}>
                  Edit
                </button>
                <button type="button" className="docs-btn" onClick={() => rotate(h)}>New URL</button>
                <button type="button" className="docs-btn"
                        onClick={() => setExpanded(view === 'history' ? null : { id: h.id, view: 'history' })}>
                  {view === 'history' ? 'Hide history' : 'History'}
                </button>
                <button type="button" className="docs-btn sched-delete" onClick={() => remove(h)}>Delete</button>
              </div>

              {view === 'test' && <TestCall hook={h} onStarted={() => { setExpanded({ id: h.id, view: 'history' }); load() }} />}
              {view === 'history' && <RunHistory webhookId={h.id} refreshKey={refreshKey} retries={h.retries} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}
