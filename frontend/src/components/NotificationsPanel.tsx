import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../types'

interface PipelineRef {
  id: string
  name: string
}

interface Channel {
  id: string
  name: string
  kind: 'slack' | 'webhook'
  url: string
  events: string[]
  app_id: string | null
  enabled: boolean
  last_sent_at: string | null
  last_error: string | null
}

const EVENTS: { id: string; label: string; hint: string }[] = [
  { id: 'run.failed', label: 'Run failed', hint: 'error, timeout, budget or middleware block' },
  { id: 'run.paused', label: 'Waiting for approval', hint: 'a Human Gate paused the run' },
  { id: 'gate.escalated', label: 'Review escalated', hint: 'a Human Gate timed out with “escalate”' },
  { id: 'schedule.auto_paused', label: 'Schedule auto-paused', hint: 'turned off after repeated failures' },
]

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

async function errorText(r: Response): Promise<string> {
  const d = await r.json().catch(() => ({}))
  return typeof d.detail === 'string' ? d.detail : r.statusText
}

interface FormState {
  name: string
  kind: 'slack' | 'webhook'
  url: string
  events: string[]
  app_id: string
}

function ChannelForm({ initial, editingId, apps, onCancel, onSaved }: {
  initial: FormState
  editingId: string | null
  apps: PipelineRef[]
  onCancel: () => void
  onSaved: () => void
}) {
  const [f, setF] = useState<FormState>(initial)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }))
  const toggleEvent = (id: string) =>
    set('events', f.events.includes(id) ? f.events.filter((e) => e !== id) : [...f.events, id])

  const save = async () => {
    if (!editingId && !f.url.trim()) { setError('Enter the URL to send alerts to.'); return }
    if (f.events.length === 0) { setError('Pick at least one event.'); return }
    setSaving(true)
    setError(null)
    const body: Record<string, unknown> = { name: f.name, events: f.events, app_id: f.app_id }
    if (f.url.trim()) body.url = f.url.trim()
    try {
      const r = editingId
        ? await fetch(`${API_BASE}/api/notifications/${encodeURIComponent(editingId)}`, {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
          })
        : await fetch(`${API_BASE}/api/notifications`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...body, kind: f.kind, app_id: f.app_id || null }),
          })
      if (!r.ok) { setError(await errorText(r)); return }
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="sched-form">
      {!editingId && (
        <label className="sched-field">
          <span>Send to</span>
          <select className="ops-select" value={f.kind} onChange={(e) => set('kind', e.target.value as FormState['kind'])}>
            <option value="slack">Slack (incoming webhook)</option>
            <option value="webhook">Any URL (JSON POST)</option>
          </select>
        </label>
      )}
      <label className="sched-field">
        <span>Name</span>
        <input className="sched-input" value={f.name} placeholder="e.g. #ops-alerts"
               onChange={(e) => set('name', e.target.value)} />
      </label>
      <label className="sched-field">
        <span>URL</span>
        <input className="sched-input sched-input--mono" value={f.url}
               placeholder={editingId ? 'Leave empty to keep the current URL'
                 : f.kind === 'slack' ? 'https://hooks.slack.com/services/…' : 'https://example.com/alerts'}
               onChange={(e) => set('url', e.target.value)} />
      </label>
      <div className="sched-field">
        <span>Events</span>
        <div>
          {EVENTS.map((ev) => (
            <label key={ev.id} className="sched-inline">
              <input type="checkbox" checked={f.events.includes(ev.id)} onChange={() => toggleEvent(ev.id)} />
              {ev.label} <span className="sched-muted">— {ev.hint}</span>
            </label>
          ))}
        </div>
      </div>
      <label className="sched-field">
        <span>Pipelines</span>
        <select className="ops-select" value={f.app_id} onChange={(e) => set('app_id', e.target.value)}>
          <option value="">Every pipeline in this project</option>
          {apps.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </label>
      <p className="sched-muted">Alerts cover scheduled and webhook runs — runs started by hand already show you the result.</p>

      {error && <div className="sched-error">{error}</div>}
      <div className="sched-form-actions">
        <button type="button" className="docs-btn" onClick={onCancel} disabled={saving}>Cancel</button>
        <button type="button" className="docs-btn docs-btn--primary" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : editingId ? 'Save changes' : 'Add channel'}
        </button>
      </div>
    </div>
  )
}

/** Where unattended-run alerts go: Slack / webhook channels, per project or per pipeline. */
export function NotificationsPanel({ apps }: { apps: PipelineRef[] }) {
  const [channels, setChannels] = useState<Channel[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<{ initial: FormState; editingId: string | null } | null>(null)
  const [testResult, setTestResult] = useState<Record<string, string>>({})

  const load = useCallback(() => {
    setLoading(true)
    fetch(`${API_BASE}/api/notifications`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error(await errorText(r)))))
      .then((d: Channel[]) => { setChannels(d); setError(null) })
      .catch((e) => setError(`Failed to load channels: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const act = async (url: string, init: RequestInit) => {
    try {
      const r = await fetch(url, init)
      if (!r.ok) { setError(await errorText(r)); return null }
      setError(null)
      const d = await r.json()
      load()
      return d
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return null
    }
  }

  const test = async (ch: Channel) => {
    setTestResult((p) => ({ ...p, [ch.id]: 'Sending…' }))
    const d = await act(`${API_BASE}/api/notifications/${encodeURIComponent(ch.id)}/test`, { method: 'POST' })
    setTestResult((p) => ({ ...p, [ch.id]: d ? (d.ok ? '✓ Delivered' : `✗ ${d.error}`) : '' }))
  }

  const remove = (ch: Channel) => {
    if (!window.confirm(`Delete "${ch.name}"? Alerts stop going there.`)) return
    act(`${API_BASE}/api/notifications/${encodeURIComponent(ch.id)}`, { method: 'DELETE' })
  }

  const appName = (id: string | null) => (id ? apps.find((a) => a.id === id)?.name ?? 'Deleted pipeline' : 'All pipelines')

  return (
    <div className="sched-panel ops-panel">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">Alerts</span>
          <span className="ops-count-badge">{channels.length} channel{channels.length !== 1 ? 's' : ''}</span>
        </div>
        <div className="ops-toolbar-right">
          <button type="button" className="ops-refresh-btn" onClick={load} disabled={loading}>{loading ? '…' : '↻'}</button>
          <button type="button" className="docs-btn docs-btn--primary" disabled={!!form}
                  onClick={() => setForm({ initial: { name: '', kind: 'slack', url: '', events: EVENTS.map((e) => e.id), app_id: '' }, editingId: null })}>
            + New channel
          </button>
        </div>
      </div>

      <div className="sched-body">
        {error && <div className="sched-error">{error}</div>}
        {form && (
          <ChannelForm key={form.editingId ?? 'new'} initial={form.initial} editingId={form.editingId} apps={apps}
                       onCancel={() => setForm(null)} onSaved={() => { setForm(null); load() }} />
        )}

        {!form && channels.length === 0 && !loading && (
          <div className="sched-empty">
            <p className="sched-empty-title">No alert channels yet</p>
            <p className="sched-muted">
              Scheduled and webhook runs happen with nobody watching. Send a Slack message or a JSON POST when one
              fails, stops at a Human Gate for approval, or a schedule pauses itself.
            </p>
          </div>
        )}

        {channels.map((ch) => (
          <div key={ch.id} className={`sched-card sched-card--${ch.enabled ? 'active' : 'paused'}`}>
            <div className="sched-card-head">
              <div className="sched-card-title">
                <span className="sched-card-name">{ch.name}</span>
                <span className={`sched-pill sched-pill--${ch.enabled ? 'active' : 'paused'}`}>{ch.kind}</span>
              </div>
              <div className="sched-muted">{appName(ch.app_id)} · <code>{ch.url}</code></div>
              <div className="sched-card-meta">
                <span>{ch.events.map((e) => EVENTS.find((x) => x.id === e)?.label ?? e).join(' · ')}</span>
              </div>
              <div className="sched-card-meta">
                {ch.last_sent_at
                  ? <span>Last sent {when(ch.last_sent_at)}
                      <span className={`sched-dot sched-dot--${ch.last_error ? 'failed' : 'completed'}`} /></span>
                  : <span className="sched-muted">Nothing sent yet</span>}
                {testResult[ch.id] && <span>{testResult[ch.id]}</span>}
              </div>
              {ch.last_error && <div className="sched-error sched-error--inline">{ch.last_error}</div>}
            </div>
            <div className="sched-actions">
              <button type="button" className="docs-btn" onClick={() => test(ch)}>Send test</button>
              <button type="button" className="docs-btn"
                      onClick={() => act(`${API_BASE}/api/notifications/${encodeURIComponent(ch.id)}`, {
                        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ enabled: !ch.enabled }),
                      })}>
                {ch.enabled ? 'Mute' : 'Unmute'}
              </button>
              <button type="button" className="docs-btn" disabled={!!form}
                      onClick={() => setForm({ initial: { name: ch.name, kind: ch.kind, url: '', events: ch.events, app_id: ch.app_id ?? '' }, editingId: ch.id })}>
                Edit
              </button>
              <button type="button" className="docs-btn sched-delete" onClick={() => remove(ch)}>Delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
