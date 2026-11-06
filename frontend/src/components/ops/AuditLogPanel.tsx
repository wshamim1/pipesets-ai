import { useCallback, useEffect, useMemo, useState } from 'react'
import { API_BASE } from '../../types'
import { downloadFile } from '../../utils/download'

export interface AuditEntry {
  id: string
  tenant_id: string
  project_id: string
  actor: string
  action: string
  target_id: string
  outcome: 'success' | 'denied'
  status: number
  method: string
  path: string
  ip: string
  created_at: string
}

interface Policy {
  retention_days: number
  actions: string[]
}

interface Filters {
  action: string
  actor: string
  outcome: '' | 'success' | 'denied'
  since: string   // yyyy-mm-dd from a date input, local day
  until: string
}

const EMPTY: Filters = { action: '', actor: '', outcome: '', since: '', until: '' }
const PAGE = 100

// Backend timestamps are naive UTC ISO strings
const toDate = (iso: string) => new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))
const fmt = (iso: string) => toDate(iso).toLocaleString()

/** The local day's start as the backend's naive UTC ISO form; `nextDay` gives the end of the day. */
function dayToUtc(day: string, nextDay = false): string {
  const d = new Date(`${day}T00:00:00`)
  if (nextDay) d.setDate(d.getDate() + 1)
  return d.toISOString().replace('Z', '')
}

/** Query string for the list and export endpoints; empty filters are left out. */
export function auditQuery(f: Filters, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams(extra)
  if (f.action) q.set('action', f.action)
  if (f.actor.trim()) q.set('actor', f.actor.trim())
  if (f.outcome) q.set('outcome', f.outcome)
  if (f.since) q.set('since', dayToUtc(f.since))
  if (f.until) q.set('until', dayToUtc(f.until, true))
  return q.toString()
}

/** "secret.create" → group "secret." — the select offers each group, then its actions. */
function actionGroups(actions: string[]): { group: string; actions: string[] }[] {
  const by = new Map<string, string[]>()
  for (const a of actions) {
    const g = `${a.split('.')[0]}.`
    by.set(g, [...(by.get(g) ?? []), a])
  }
  return [...by.entries()].map(([group, list]) => ({ group, actions: list }))
}

async function errorText(res: Response): Promise<string> {
  if (res.status === 403) return 'You need the audit:read permission in this workspace (workspace owners have it).'
  const body = await res.json().catch(() => ({}))
  return typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`
}

/** Settings → Audit log: who changed keys, secrets, access and publishing, and who was refused. */
export function AuditLogPanel() {
  const [policy, setPolicy] = useState<Policy | null>(null)
  const [draft, setDraft] = useState<Filters>(EMPTY)
  const [filters, setFilters] = useState<Filters>(EMPTY)
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [nextBefore, setNextBefore] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async (f: Filters, before?: string) => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API_BASE}/api/audit-log?${auditQuery(f, { limit: String(PAGE), ...(before ? { before } : {}) })}`)
      if (!res.ok) {
        setError(await errorText(res))
        return
      }
      const page: { entries: AuditEntry[]; next_before: string | null } = await res.json()
      setEntries((prev) => (before ? [...prev, ...page.entries] : page.entries))
      setNextBefore(page.next_before)
    } catch {
      setError('Backend not reachable.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch(`${API_BASE}/api/audit-log/policy`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setPolicy)
      .catch(() => setPolicy(null))
  }, [])

  useEffect(() => { void load(filters) }, [filters, load])

  const groups = useMemo(() => actionGroups(policy?.actions ?? []), [policy])
  const dirty = JSON.stringify(draft) !== JSON.stringify(filters)
  const filtered = JSON.stringify(filters) !== JSON.stringify(EMPTY)
  const exportAs = (format: 'csv' | 'jsonl') => {
    downloadFile(`${API_BASE}/api/audit-log/export?${auditQuery(filters, { format })}`, `audit-log.${format}`)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }

  return (
    <div className="ops-panel">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">Audit log</span>
          <span className="ops-count-badge">{entries.length}{nextBefore ? '+' : ''} entries</span>
        </div>
        <div className="ops-toolbar-right">
          <button type="button" className="ops-refresh-btn" onClick={() => exportAs('csv')}>⬇ CSV</button>
          <button type="button" className="ops-refresh-btn" onClick={() => exportAs('jsonl')}>⬇ JSON Lines</button>
          <button type="button" className="ops-refresh-btn" onClick={() => load(filters)} disabled={loading}>
            {loading ? 'Loading…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      <div className="apikeys-body">
        <div className="apikeys-intro">
          Every change to API keys, secrets, members and access, workspaces, publishing and other settings, and
          every refused attempt. Request bodies are never stored, so key and secret values can't appear here.{' '}
          {policy && (policy.retention_days
            ? <>Entries are kept for <strong>{policy.retention_days} days</strong> (set by the server operator with <code>AUDIT_RETENTION_DAYS</code>).</>
            : <>Entries are kept <strong>forever</strong> (<code>AUDIT_RETENTION_DAYS=0</code>).</>)}
          {' '}Exports are logged too.
        </div>

        <form className="apikeys-form" onSubmit={(e) => { e.preventDefault(); setFilters(draft) }}>
          <select className="ops-select" aria-label="Action" value={draft.action}
            onChange={(e) => setDraft({ ...draft, action: e.target.value })}>
            <option value="">All actions</option>
            {groups.map(({ group, actions }) => (
              <optgroup key={group} label={group.slice(0, -1).replaceAll('_', ' ')}>
                <option value={group}>All {group.slice(0, -1).replaceAll('_', ' ')} actions</option>
                {actions.map((a) => <option key={a} value={a}>{a}</option>)}
              </optgroup>
            ))}
          </select>
          <input type="text" className="ops-select auditlog-actor" placeholder="User id" aria-label="User"
            value={draft.actor} onChange={(e) => setDraft({ ...draft, actor: e.target.value })} />
          <select className="ops-select" aria-label="Outcome" value={draft.outcome}
            onChange={(e) => setDraft({ ...draft, outcome: e.target.value as Filters['outcome'] })}>
            <option value="">Any outcome</option>
            <option value="success">Succeeded</option>
            <option value="denied">Denied</option>
          </select>
          <label className="apikeys-inline">From
            <input type="date" className="ops-select" value={draft.since}
              onChange={(e) => setDraft({ ...draft, since: e.target.value })} />
          </label>
          <label className="apikeys-inline">To
            <input type="date" className="ops-select" value={draft.until}
              onChange={(e) => setDraft({ ...draft, until: e.target.value })} />
          </label>
          <button type="submit" className="ops-refresh-btn" disabled={!dirty}>Apply</button>
          {(dirty || filtered) && (
            <button type="button" className="ops-link-btn" onClick={() => { setDraft(EMPTY); setFilters(EMPTY) }}>Clear</button>
          )}
        </form>

        {error && <div className="apikeys-error" role="alert">{error}</div>}

        <div className="apikeys-table auditlog-table">
          {entries.length > 0 && (
            <div className="ops-table-header">
              <span className="apikeys-col-date auditlog-col-time">Time</span>
              <span className="auditlog-col-actor">User</span>
              <span className="auditlog-col-action">Action</span>
              <span className="auditlog-col-target">Target</span>
              <span className="apikeys-col-status">Outcome</span>
              <span className="auditlog-col-project">Project</span>
              <span className="auditlog-col-ip">IP</span>
            </div>
          )}
          <div className="ops-list">
            {entries.length === 0 && !loading && !error && (
              <div className="ops-empty">No audit entries{filtered ? ' match these filters' : ' yet'}.</div>
            )}
            {entries.map((e) => (
              <div key={e.id} className={`ops-pipeline-row${e.outcome === 'denied' ? ' auditlog-row--denied' : ''}`}
                title={`${e.method} ${e.path} → ${e.status}`}>
                <span className="apikeys-col-date auditlog-col-time">{fmt(e.created_at)}</span>
                <span className="auditlog-col-actor">{e.actor || '—'}</span>
                <span className="auditlog-col-action"><code>{e.action}</code></span>
                <span className="auditlog-col-target">{e.target_id || '—'}</span>
                <span className="apikeys-col-status">
                  <span className={`ops-status-pill auditlog-pill--${e.outcome}`}>{e.outcome}</span>
                </span>
                <span className="auditlog-col-project">{e.project_id || '—'}</span>
                <span className="auditlog-col-ip">{e.ip || '—'}</span>
              </div>
            ))}
          </div>
        </div>
        {nextBefore && (
          <button type="button" className="ops-refresh-btn auditlog-more" disabled={loading}
            onClick={() => load(filters, nextBefore)}>
            {loading ? 'Loading…' : 'Load older entries'}
          </button>
        )}
      </div>
    </div>
  )
}
