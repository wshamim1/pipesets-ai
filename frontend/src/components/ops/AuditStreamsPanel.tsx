import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { API_BASE } from '../../types'
import { HelpLink } from '../docs/HelpLink'
import '../../styles/sso.css'

/** Settings → Audit log → Streaming: send this workspace's audit log to a SIEM (backend services/audit_stream.py). */

type Kind = 'webhook' | 'splunk_hec' | 'datadog'

interface Sink {
  id: string
  name: string
  kind: Kind
  kind_label: string
  url: string
  token_set: boolean
  enabled: boolean
  delivered: number
  last_delivered_at: string | null
  last_error: string
  failures: number
  next_attempt_at: string | null
}

const KIND_HELP: Record<Kind, { url: string; urlPlaceholder: string; token: string; tokenHint: string }> = {
  webhook: { url: 'Endpoint URL', urlPlaceholder: 'https://siem.example.com/ingest/pipesets', token: 'Signing secret (optional)',
             tokenHint: 'Each batch is signed: X-Pipesets-Signature: sha256=<HMAC-SHA256 of the body>.' },
  splunk_hec: { url: 'HEC URL', urlPlaceholder: 'https://splunk.example.com:8088/services/collector/event', token: 'HEC token',
                tokenHint: 'Events arrive with sourcetype pipesets:audit.' },
  datadog: { url: 'Intake URL (leave empty for US1)', urlPlaceholder: 'https://http-intake.logs.datadoghq.eu/api/v2/logs',
             token: 'Datadog API key', tokenHint: 'Logs arrive with source pipesets and a tenant tag.' },
}

const toDate = (iso: string) => new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))
const fmt = (iso: string | null) => (iso ? toDate(iso).toLocaleString() : 'never')

async function detail(res: Response): Promise<string> {
  if (res.status === 403) return 'You need the audit:admin permission (workspace owners have it).'
  try {
    const body = await res.json()
    return typeof body.detail === 'string' ? body.detail : res.statusText
  } catch {
    return res.statusText
  }
}

export function AuditStreamsPanel() {
  const [sinks, setSinks] = useState<Sink[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [allowed, setAllowed] = useState(true)
  const [form, setForm] = useState<{ kind: Kind; name: string; url: string; token: string; start: 'now' | 'all' } | null>(null)

  const load = useCallback(async () => {
    const res = await fetch(`${API_BASE}/api/audit-log/sinks`)
    if (res.status === 403) {
      setAllowed(false)
      return
    }
    if (res.ok) setSinks((await res.json()).sinks)
  }, [])

  useEffect(() => { load() }, [load])

  const call = async (path: string, method: string, body?: unknown) => {
    const res = await fetch(`${API_BASE}/api/audit-log/sinks${path}`, {
      method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) throw new Error(await detail(res))
    return res.json()
  }

  const run = async (fn: () => Promise<string | void>) => {
    try {
      const msg = await fn()
      setError('')
      setNotice(msg || '')
      load()
    } catch (e) {
      setNotice('')
      setError(e instanceof Error ? e.message : 'Something went wrong')
    }
  }

  const add = (e: FormEvent) => {
    e.preventDefault()
    if (!form) return
    run(async () => {
      const sink = await call('', 'POST', form)
      setForm(null)
      return `Added ${sink.name}. New entries are sent within a few seconds; use Test to check the connection.`
    })
  }

  if (!allowed) return null

  return (
    <div className="ops-panel audit-streams">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">Streaming</span>
          <span className="ops-count-badge">{sinks.length} destination{sinks.length === 1 ? '' : 's'}</span>
          <HelpLink page="11-settings-admin" section="audit-log-streaming" label="Streaming the audit log" />
        </div>
        <div className="ops-toolbar-right">
          {!form && (
            <button type="button" className="ops-refresh-btn"
              onClick={() => setForm({ kind: 'webhook', name: '', url: '', token: '', start: 'now' })}>
              + Add destination
            </button>
          )}
        </div>
      </div>
      <div className="sso-body">
        {error && <div className="sso-error" role="alert">{error}</div>}
        {notice && <div className="sso-notice" role="status">{notice}</div>}

        {form && (
          <form className="sso-card" onSubmit={add}>
            <h3>New destination</h3>
            <label className="sso-field">
              <span>Type</span>
              <select className="field-select" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as Kind })}>
                <option value="webhook">Webhook (JSON)</option>
                <option value="splunk_hec">Splunk HTTP Event Collector</option>
                <option value="datadog">Datadog Logs</option>
              </select>
            </label>
            <label className="sso-field">
              <span>Name</span>
              <input className="field-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Security SIEM" />
            </label>
            <label className="sso-field">
              <span>{KIND_HELP[form.kind].url}</span>
              <input className="field-input code-font" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })}
                placeholder={KIND_HELP[form.kind].urlPlaceholder} required={form.kind !== 'datadog'} />
            </label>
            <label className="sso-field">
              <span>{KIND_HELP[form.kind].token}</span>
              <input className="field-input" type="password" autoComplete="off" value={form.token}
                onChange={(e) => setForm({ ...form, token: e.target.value })} required={form.kind !== 'webhook'} />
              <small>{KIND_HELP[form.kind].tokenHint} Stored encrypted; never shown again.</small>
            </label>
            <label className="sso-field">
              <span>Start from</span>
              <select className="field-select" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value as 'now' | 'all' })}>
                <option value="now">New entries only</option>
                <option value="all">Everything still in the log (backfill)</option>
              </select>
            </label>
            <div className="sso-actions">
              <button type="submit" className="save-btn">Add destination</button>
              <button type="button" className="ops-link-btn" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}

        {!form && sinks.length === 0 && (
          <div className="ops-empty">
            Send every audit entry to your own systems (Splunk, Datadog or any HTTPS endpoint) as it happens. Deliveries are
            retried until they succeed, in order, so an outage on your side loses nothing.
          </div>
        )}

        {sinks.map((s) => (
          <div key={s.id} className="sso-card">
            <div className="sso-card-head">
              <h3>{s.name}</h3>
              <span className="ops-count-badge">{s.kind_label}</span>
              <span className="ops-count-badge">{!s.enabled ? 'Paused' : s.failures ? `Failing (${s.failures})` : 'Streaming'}</span>
              <div className="sso-card-buttons">
                <button type="button" className="ops-refresh-btn" onClick={() => run(async () => {
                  const r = await call(`/${s.id}/test`, 'POST')
                  if (!r.ok) throw new Error(`${s.name}: ${r.detail}`)
                  return `${s.name}: ${r.detail}`
                })}>Test</button>
                <button type="button" className="ops-refresh-btn" onClick={() => run(async () => {
                  await call(`/${s.id}`, 'PATCH', { enabled: !s.enabled })
                })}>{s.enabled ? 'Pause' : s.failures ? 'Retry now' : 'Resume'}</button>
                <button type="button" className="ops-danger-btn ops-danger-btn--sm" onClick={() => {
                  if (window.confirm(`Stop streaming to ${s.name}?`)) run(async () => { await call(`/${s.id}`, 'DELETE') })
                }}>Remove</button>
              </div>
            </div>
            <div className="sso-meta">
              <code>{s.url}</code> · {s.delivered.toLocaleString()} sent · last delivery {fmt(s.last_delivered_at)}
              {s.failures > 0 && s.next_attempt_at && <> · next try {fmt(s.next_attempt_at)}</>}
            </div>
            {s.last_error && <div className="sso-error">{s.last_error}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}
