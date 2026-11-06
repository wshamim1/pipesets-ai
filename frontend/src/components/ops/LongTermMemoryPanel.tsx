import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../../types'

export interface Fact {
  id: string
  subject: string
  content: string
  source: 'extracted' | 'manual'
  app_id: string | null
  created_at: string
  updated_at: string
  last_used_at: string | null
}

interface UserSummary {
  subject: string
  facts: number
  last_updated: string
}

interface Settings {
  enabled: boolean
  can_change: boolean
}

// Backend timestamps are naive UTC ISO strings
const fmt = (iso: string | null) => (iso ? new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleString() : '—')

async function errorText(res: Response): Promise<string> {
  if (res.status === 403) return 'You need write access to apps in this project (or, for the switch, to be a workspace owner).'
  const body = await res.json().catch(() => ({}))
  return typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`
}

/** Monitor → Sessions → Long-term: what is remembered about each end user, with delete and forget. */
export function LongTermMemoryPanel() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [users, setUsers] = useState<UserSummary[]>([])
  const [selected, setSelected] = useState('')
  const [facts, setFacts] = useState<Fact[]>([])
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')

  const loadUsers = useCallback(async () => {
    try {
      const [s, u] = await Promise.all([fetch(`${API_BASE}/api/memory/long-term/settings`),
        fetch(`${API_BASE}/api/memory/long-term/users`)])
      if (s.ok) setSettings(await s.json())
      if (u.ok) {
        const list: UserSummary[] = (await u.json()).users
        setUsers(list)
        setSelected((cur) => (cur && list.some((x) => x.subject === cur) ? cur : list[0]?.subject ?? ''))
      } else setError(await errorText(u))
    } catch {
      setError('Backend not reachable.')
    }
  }, [])

  const loadFacts = useCallback(async (user: string) => {
    if (!user) { setFacts([]); return }
    const res = await fetch(`${API_BASE}/api/memory/long-term/facts?user=${encodeURIComponent(user)}`).catch(() => null)
    if (res?.ok) setFacts((await res.json()).facts)
  }, [])

  useEffect(() => { void loadUsers() }, [loadUsers])
  useEffect(() => { void loadFacts(selected) }, [selected, loadFacts])

  const call = async (url: string, init: RequestInit) => {
    setError('')
    const res = await fetch(`${API_BASE}${url}`, init).catch(() => null)
    if (!res) { setError('Backend not reachable.'); return false }
    if (!res.ok) { setError(await errorText(res)); return false }
    return true
  }

  const toggle = async () => {
    if (!settings) return
    if (await call('/api/memory/long-term/settings', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: !settings.enabled }),
    })) setSettings({ ...settings, enabled: !settings.enabled })
  }

  const removeFact = async (f: Fact) => {
    if (await call(`/api/memory/long-term/facts/${f.id}`, { method: 'DELETE' })) { void loadFacts(selected); void loadUsers() }
  }

  const forget = async () => {
    if (!window.confirm(`Forget everything remembered about “${selected}”? This can't be undone.`)) return
    if (await call(`/api/memory/long-term/users/${encodeURIComponent(selected)}`, { method: 'DELETE' })) {
      setSelected('')
      void loadUsers()
    }
  }

  const addFact = async () => {
    if (!draft.trim() || !selected) return
    if (await call('/api/memory/long-term/facts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: selected, content: draft.trim() }),
    })) { setDraft(''); void loadFacts(selected); void loadUsers() }
  }

  return (
    <div className="ops-panel">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">Long-term memory</span>
          {settings && (
            <span className={`ops-status-pill ${settings.enabled ? 'ops-status-pill--published' : 'ops-status-pill--draft'}`}>
              {settings.enabled ? 'On for this workspace' : 'Off for this workspace'}
            </span>
          )}
        </div>
        <div className="ops-toolbar-right">
          {settings?.can_change && (
            <button type="button" className="ops-refresh-btn" onClick={toggle}>
              {settings.enabled ? 'Turn off' : 'Turn on'}
            </button>
          )}
          <button type="button" className="ops-refresh-btn" onClick={loadUsers}>↻ Refresh</button>
        </div>
      </div>

      <div className="apikeys-body">
        <div className="apikeys-intro">
          With long-term memory on here and in a pipeline's Memory node, facts each user states — preferences, profile,
          goals — are remembered (with PII removed) and recalled in their later sessions. The user is whoever is signed
          in on the canvas, or the <code>user</code> field on API and MCP runs. Turning it off stops recall and learning;
          what is remembered stays until deleted here.
        </div>

        {error && <div className="apikeys-error" role="alert">{error}</div>}

        <div className="ltm-layout">
          <div className="ltm-users" role="list" aria-label="Users">
            {users.length === 0 && <div className="ops-empty">Nothing remembered yet.</div>}
            {users.map((u) => (
              <button key={u.subject} type="button" role="listitem"
                className={`ltm-user${u.subject === selected ? ' ltm-user--active' : ''}`}
                onClick={() => setSelected(u.subject)}>
                <span className="ltm-user-name">{u.subject}</span>
                <span className="ltm-user-meta">{u.facts} fact{u.facts === 1 ? '' : 's'}</span>
              </button>
            ))}
          </div>

          {selected && (
            <div className="ltm-facts">
              <div className="ltm-facts-head">
                <strong>{selected}</strong>
                <button type="button" className="ops-link-btn" onClick={forget}>Forget this user</button>
              </div>
              <div className="ops-list">
                {facts.map((f) => (
                  <div key={f.id} className="ops-pipeline-row" title={`Learned ${fmt(f.created_at)}${f.app_id ? ` in ${f.app_id}` : ''}`}>
                    <span className="ltm-fact">{f.content}</span>
                    <span className="ltm-fact-meta">{f.source === 'manual' ? 'added by hand' : `last used ${fmt(f.last_used_at)}`}</span>
                    <button type="button" className="ops-link-btn" aria-label={`Delete “${f.content}”`} onClick={() => removeFact(f)}>
                      Delete
                    </button>
                  </div>
                ))}
              </div>
              <form className="apikeys-form" onSubmit={(e) => { e.preventDefault(); void addFact() }}>
                <input type="text" className="ops-select ltm-add" placeholder="Add a fact, e.g. Prefers metric units"
                  aria-label="New fact" value={draft} maxLength={300} onChange={(e) => setDraft(e.target.value)} />
                <button type="submit" className="ops-refresh-btn" disabled={!draft.trim()}>Add</button>
              </form>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
