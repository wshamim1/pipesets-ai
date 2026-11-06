import { useCallback, useEffect, useMemo, useState } from 'react'
import { API_BASE } from '../../types'
import { useTenantContext } from '../../context/TenantContext'
import { ReadOnlyFlow } from '../ReadOnlyFlow'
import '../../styles/admin-console.css'

/** Settings → Admin console: every user, workspace and pipeline on the server (routers/admin.py). */

type Tab = 'overview' | 'users' | 'workspaces' | 'pipelines' | 'audit'

interface Overview {
  users: number; users_disabled: number; server_admins: number; active_sessions: number
  workspaces: number; projects: number; pipelines: number; pipelines_published: number
  runs_7d: number; cost_7d: number
}
interface AdminUser {
  id: string; email: string; display_name: string; status: string; created_at: string
  last_seen_at: string | null; active_sessions: number; pipelines: number; has_password: boolean
  server_admin: boolean; server_admin_source: 'flag' | 'PIPESETS_SERVER_ADMINS' | null
  workspaces: { id: string; name: string; role: string }[]
}
interface Workspace {
  id: string; name: string; slug: string; status: string; created_at: string; members: number
  projects: number; pipelines: number; last_activity: string | null; owners: string[]; is_member: boolean
}
interface AdminApp {
  id: string; name: string; description: string; status: string; version: number; updated_at: string
  tenant_id: string; workspace: string | null; project: string | null; owner: string | null
  nodes: number; runs_30d: number
}
interface AuditEntry {
  id: string; created_at: string; action: string; outcome: string; actor: string; actor_email: string | null
  workspace: string | null; target_id: string; path: string
}
interface FlowPreview { id: string; name: string; workspace: string | null; flow_data: { nodes: any[]; edges: any[] } }

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'users', label: 'Users' },
  { id: 'workspaces', label: 'Workspaces' },
  { id: 'pipelines', label: 'Pipelines' },
  { id: 'audit', label: 'Audit log' },
]

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/api/admin${path}`, {
    ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

function ago(iso: string | null): string {
  if (!iso) return 'never'
  const s = (Date.now() - new Date(iso.endsWith('Z') ? iso : `${iso}Z`).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export function AdminConsolePanel() {
  const { scope, refresh, setTenantId } = useTenantContext()
  const userId = scope.userId
  const [tab, setTab] = useState<Tab>('overview')
  const [overview, setOverview] = useState<Overview | null>(null)
  const [users, setUsers] = useState<AdminUser[]>([])
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [apps, setApps] = useState<AdminApp[]>([])
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [query, setQuery] = useState('')
  const [wsFilter, setWsFilter] = useState('')
  const [auditFilter, setAuditFilter] = useState('')
  const [preview, setPreview] = useState<FlowPreview | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const load = useCallback(async () => {
    try {
      const [o, u, w, a, l] = await Promise.all([
        api<Overview>('/overview'),
        api<{ users: AdminUser[] }>('/users'),
        api<{ workspaces: Workspace[] }>('/workspaces'),
        api<{ apps: AdminApp[] }>('/apps'),
        api<{ entries: AuditEntry[] }>(`/audit?limit=200${auditFilter ? `&action=${encodeURIComponent(auditFilter)}` : ''}`),
      ])
      setOverview(o); setUsers(u.users); setWorkspaces(w.workspaces); setApps(a.apps); setAudit(l.entries)
    } catch (e) {
      setNotice({ kind: 'error', text: e instanceof Error ? e.message : String(e) })
    }
  }, [auditFilter])

  useEffect(() => { void load() }, [load])

  const act = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key)
    setNotice(null)
    try {
      await fn()
      setNotice({ kind: 'ok', text: ok })
      await load()
    } catch (e) {
      setNotice({ kind: 'error', text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(null)
    }
  }

  const patchUser = (u: AdminUser, body: Record<string, unknown>, ok: string) =>
    act(`u-${u.id}`, () => api(`/users/${u.id}`, { method: 'PATCH', body: JSON.stringify(body) }), ok)

  const setPassword = (u: AdminUser) => {
    const pw = window.prompt(`New password for ${u.email} (at least 8 characters). They'll be signed out everywhere.`)
    if (!pw) return
    void act(`u-${u.id}`, () => api(`/users/${u.id}/password`, { method: 'POST', body: JSON.stringify({ password: pw }) }),
      `Password set for ${u.email}`)
  }

  const deleteUser = (u: AdminUser) => {
    if (!window.confirm(`Delete ${u.email}? Their memberships and sessions go too. This can't be undone.`)) return
    void act(`u-${u.id}`, () => api(`/users/${u.id}`, { method: 'DELETE' }), `Deleted ${u.email}`)
  }

  const joinWorkspace = (w: Workspace) =>
    act(`w-${w.id}`, async () => {
      await api(`/workspaces/${w.id}/join`, { method: 'POST' })
      await refresh()
    }, `You're now an owner of ${w.name}. Switch to it from the workspace menu in the header, or use "Switch".`)

  const switchTo = (w: Workspace) => {
    setTenantId(w.id)
    window.location.reload()   // every view reloads its data for the new workspace
  }

  const deleteWorkspace = (w: Workspace) => {
    if (!window.confirm(`Delete the workspace "${w.name}" with its ${w.pipelines} pipelines, runs, keys and members? This can't be undone.`)) return
    void act(`w-${w.id}`, () => api(`/workspaces/${w.id}`, { method: 'DELETE' }), `Deleted ${w.name}`)
  }

  const openPreview = (a: AdminApp) =>
    act(`a-${a.id}`, async () => setPreview(await api<FlowPreview>(`/apps/${a.id}`)), `Opened ${a.name} (view only)`)

  const needle = query.trim().toLowerCase()
  const shownUsers = useMemo(() => users.filter((u) => !needle || `${u.email} ${u.display_name}`.toLowerCase().includes(needle)), [users, needle])
  const shownApps = useMemo(() => apps.filter((a) => (!wsFilter || a.tenant_id === wsFilter)
    && (!needle || `${a.name} ${a.workspace ?? ''} ${a.owner ?? ''}`.toLowerCase().includes(needle))), [apps, wsFilter, needle])

  return (
    <div className="admin-console">
      <div className="admin-tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
            className={`admin-tab${tab === t.id ? ' admin-tab--active' : ''}`} onClick={() => { setTab(t.id); setQuery('') }}>
            {t.label}
            {t.id === 'users' && <span className="admin-tab-count">{users.length}</span>}
            {t.id === 'workspaces' && <span className="admin-tab-count">{workspaces.length}</span>}
            {t.id === 'pipelines' && <span className="admin-tab-count">{apps.length}</span>}
          </button>
        ))}
        <button type="button" className="ops-refresh-btn admin-reload" onClick={() => void load()}>↻ Reload</button>
      </div>

      {notice && <div className={`admin-notice admin-notice--${notice.kind}`} role="status">{notice.text}</div>}

      {tab === 'overview' && overview && (
        <div className="admin-stats">
          {[
            ['Users', overview.users, overview.users_disabled ? `${overview.users_disabled} disabled` : 'all active'],
            ['Server admins', overview.server_admins, 'can open this console'],
            ['Signed in now', overview.active_sessions, 'users with a live session'],
            ['Workspaces', overview.workspaces, `${overview.projects} projects`],
            ['Pipelines', overview.pipelines, `${overview.pipelines_published} published`],
            ['Runs · 7 days', overview.runs_7d, `$${overview.cost_7d.toFixed(2)} model spend`],
          ].map(([label, value, hint]) => (
            <div key={label as string} className="admin-stat">
              <span className="admin-stat-label">{label}</span>
              <span className="admin-stat-value">{value}</span>
              <span className="admin-stat-hint">{hint}</span>
            </div>
          ))}
        </div>
      )}

      {(tab === 'users' || tab === 'pipelines') && (
        <div className="admin-toolbar">
          <input type="search" className="ops-select admin-search" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder={tab === 'users' ? 'Search by name or email…' : 'Search by pipeline, workspace or owner…'} />
          {tab === 'pipelines' && (
            <select className="ops-select" value={wsFilter} onChange={(e) => setWsFilter(e.target.value)} aria-label="Workspace">
              <option value="">All workspaces</option>
              {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          )}
        </div>
      )}

      {tab === 'users' && (
        <div className="admin-table" role="table" aria-label="Users">
          <div className="admin-row admin-row--head" role="row">
            <span>User</span><span>Workspaces</span><span>Last seen</span><span>Pipelines</span><span />
          </div>
          {shownUsers.map((u) => {
            const me = u.id === userId
            return (
              <div key={u.id} className={`admin-row${u.status !== 'active' ? ' admin-row--muted' : ''}`} role="row">
                <span className="admin-user">
                  <strong>{u.display_name || u.email}{me && <span className="admin-you"> (you)</span>}</strong>
                  <span className="admin-sub">{u.email}</span>
                  <span className="admin-tags">
                    {u.server_admin && <span className="admin-tag admin-tag--admin" title={u.server_admin_source ?? ''}>Server admin</span>}
                    {u.status !== 'active' && <span className="admin-tag admin-tag--off">Disabled</span>}
                    {!u.has_password && <span className="admin-tag">No password</span>}
                  </span>
                </span>
                <span className="admin-sub">
                  {u.workspaces.length ? u.workspaces.map((w) => `${w.name} (${w.role})`).join(', ') : '—'}
                </span>
                <span className="admin-sub">{ago(u.last_seen_at)}{u.active_sessions ? ` · ${u.active_sessions} live` : ''}</span>
                <span className="admin-sub">{u.pipelines}</span>
                <span className="admin-actions">
                  <button type="button" className="ops-link-btn" disabled={busy !== null || me}
                    onClick={() => void patchUser(u, { status: u.status === 'active' ? 'disabled' : 'active' },
                      `${u.email} ${u.status === 'active' ? 'disabled and signed out' : 'enabled'}`)}>
                    {u.status === 'active' ? 'Disable' : 'Enable'}
                  </button>
                  <button type="button" className="ops-link-btn" disabled={busy !== null || me || u.server_admin_source === 'PIPESETS_SERVER_ADMINS'}
                    onClick={() => void patchUser(u, { server_admin: !u.server_admin },
                      `${u.email} is ${u.server_admin ? 'no longer' : 'now'} a server admin`)}>
                    {u.server_admin ? 'Revoke admin' : 'Make admin'}
                  </button>
                  <button type="button" className="ops-link-btn" disabled={busy !== null} onClick={() => setPassword(u)}>Set password</button>
                  <button type="button" className="ops-link-btn" disabled={busy !== null || !u.active_sessions}
                    onClick={() => void act(`u-${u.id}`, () => api(`/users/${u.id}/sign-out`, { method: 'POST' }), `${u.email} signed out everywhere`)}>
                    Sign out
                  </button>
                  <button type="button" className="ops-link-btn admin-danger" disabled={busy !== null || me} onClick={() => deleteUser(u)}>Delete</button>
                </span>
              </div>
            )
          })}
          {shownUsers.length === 0 && <div className="ops-empty">No users match.</div>}
        </div>
      )}

      {tab === 'workspaces' && (
        <div className="admin-table" role="table" aria-label="Workspaces">
          <div className="admin-row admin-row--head" role="row">
            <span>Workspace</span><span>Owners</span><span>Contents</span><span>Last change</span><span />
          </div>
          {workspaces.map((w) => (
            <div key={w.id} className="admin-row" role="row">
              <span className="admin-user">
                <strong>{w.name}{w.id === scope.tenantId && <span className="admin-you"> (current)</span>}</strong>
                <span className="admin-sub">{w.id}</span>
              </span>
              <span className="admin-sub">{w.owners.join(', ') || '—'}</span>
              <span className="admin-sub">{w.members} members · {w.projects} projects · {w.pipelines} pipelines</span>
              <span className="admin-sub">{ago(w.last_activity)}</span>
              <span className="admin-actions">
                <button type="button" className="ops-link-btn" disabled={busy !== null}
                  onClick={() => { setWsFilter(w.id); setTab('pipelines') }}>Pipelines</button>
                {w.is_member
                  ? w.id !== scope.tenantId && <button type="button" className="ops-link-btn" onClick={() => switchTo(w)}>Switch</button>
                  : <button type="button" className="ops-link-btn" disabled={busy !== null} onClick={() => void joinWorkspace(w)}
                      title="Become an owner so you can open and edit its pipelines. Recorded in the audit log.">Join as owner</button>}
                <button type="button" className="ops-link-btn admin-danger" disabled={busy !== null || w.id === scope.tenantId}
                  onClick={() => deleteWorkspace(w)}>Delete</button>
              </span>
            </div>
          ))}
        </div>
      )}

      {tab === 'pipelines' && (
        <div className="admin-table" role="table" aria-label="Pipelines">
          <div className="admin-row admin-row--head" role="row">
            <span>Pipeline</span><span>Workspace</span><span>Owner</span><span>Runs · 30d</span><span />
          </div>
          {shownApps.map((a) => (
            <div key={a.id} className="admin-row" role="row">
              <span className="admin-user">
                <strong>{a.name}</strong>
                <span className="admin-sub">
                  <span className={`admin-tag${a.status === 'published' ? ' admin-tag--live' : ''}`}>
                    {a.status === 'published' ? `v${a.version} published` : 'Draft'}
                  </span>{' '}{a.nodes} nodes · updated {ago(a.updated_at)}
                </span>
              </span>
              <span className="admin-sub">{a.workspace ?? '—'}{a.project ? ` / ${a.project}` : ''}</span>
              <span className="admin-sub">{a.owner ?? '—'}</span>
              <span className="admin-sub">{a.runs_30d}</span>
              <span className="admin-actions">
                <button type="button" className="ops-link-btn" disabled={busy !== null} onClick={() => void openPreview(a)}>View</button>
              </span>
            </div>
          ))}
          {shownApps.length === 0 && <div className="ops-empty">No pipelines match.</div>}
        </div>
      )}

      {tab === 'audit' && (
        <>
          <div className="admin-toolbar">
            <select className="ops-select" value={auditFilter} onChange={(e) => setAuditFilter(e.target.value)} aria-label="Action">
              <option value="">Every action</option>
              <option value="admin.">Admin console</option>
              <option value="user.">Users</option>
              <option value="tenant.">Workspaces</option>
              <option value="secret.">Secrets</option>
              <option value="app.">Pipelines</option>
              <option value="api_key.">API keys</option>
            </select>
            <span className="admin-sub">Every workspace, newest first. Each workspace's own log is under Audit log.</span>
          </div>
          <div className="admin-table" role="table" aria-label="Audit log">
            <div className="admin-row admin-row--head admin-row--audit" role="row">
              <span>When</span><span>Who</span><span>Action</span><span>Workspace</span><span>Result</span>
            </div>
            {audit.map((e) => (
              <div key={e.id} className="admin-row admin-row--audit" role="row">
                <span className="admin-sub" title={e.created_at}>{ago(e.created_at)}</span>
                <span className="admin-sub">{e.actor_email ?? e.actor}</span>
                <span><code className="admin-code">{e.action}</code> <span className="admin-sub">{e.target_id}</span></span>
                <span className="admin-sub">{e.workspace ?? '—'}</span>
                <span className={`admin-tag${e.outcome === 'denied' ? ' admin-tag--off' : ''}`}>{e.outcome}</span>
              </div>
            ))}
            {audit.length === 0 && <div className="ops-empty">No entries.</div>}
          </div>
        </>
      )}

      {preview && (
        <div className="modal-backdrop" onClick={() => setPreview(null)}>
          <div className="modal-card pipeline-preview-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="pipeline-preview-title">
                <div className="pipeline-preview-crumbs"><strong>{preview.name}</strong></div>
                <span className="field-hint">
                  {preview.workspace} · {preview.flow_data.nodes.length} nodes · view only. Join the workspace to edit it.
                </span>
              </div>
              <button type="button" className="modal-close-btn" aria-label="Close" onClick={() => setPreview(null)}>✕</button>
            </div>
            <div className="pipeline-preview-body">
              <ReadOnlyFlow nodes={preview.flow_data.nodes} edges={preview.flow_data.edges} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
