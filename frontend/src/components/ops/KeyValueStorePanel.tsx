import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../../types'

export interface StoreEntry {
  namespace: string
  key: string
  value: unknown
  expires_at: string | null
  created_at: string
  updated_at: string
}

interface SubjectSummary {
  subject: string            // "" = shared across the project
  entries: number
  namespaces: string[]
  last_updated: string
}

const SHARED = 'Shared (project)'
const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never')
const show = (v: unknown) => JSON.stringify(v)

async function errorText(res: Response): Promise<string> {
  if (res.status === 403) return 'You need write access to apps in this project.'
  const body = await res.json().catch(() => ({}))
  return typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`
}

/** Parses the JSON typed into an editor; plain text that isn't JSON is stored as a string. */
function parseValue(text: string): unknown {
  try { return JSON.parse(text) } catch { return text }
}

/** Monitor → Sessions → Store: what agents saved with the Key-Value Store tool, per user and namespace. */
export function KeyValueStorePanel() {
  const [subjects, setSubjects] = useState<SubjectSummary[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [namespace, setNamespace] = useState('')
  const [entries, setEntries] = useState<StoreEntry[]>([])
  const [editing, setEditing] = useState<{ namespace: string; key: string; text: string } | null>(null)
  const [draft, setDraft] = useState({ namespace: 'default', key: '', value: '' })
  const [error, setError] = useState('')

  const loadSubjects = useCallback(async () => {
    const res = await fetch(`${API_BASE}/api/memory/store/subjects`).catch(() => null)
    if (!res) { setError('Backend not reachable.'); return }
    if (!res.ok) { setError(await errorText(res)); return }
    const list: SubjectSummary[] = (await res.json()).subjects
    setSubjects(list)
    setSelected((cur) => (cur !== null && list.some((s) => s.subject === cur) ? cur : list[0]?.subject ?? null))
  }, [])

  const loadEntries = useCallback(async (subject: string | null, ns: string) => {
    if (subject === null) { setEntries([]); return }
    const q = new URLSearchParams({ subject, ...(ns ? { namespace: ns } : {}) })
    const res = await fetch(`${API_BASE}/api/memory/store/entries?${q}`).catch(() => null)
    if (res?.ok) setEntries((await res.json()).entries)
  }, [])

  useEffect(() => { void loadSubjects() }, [loadSubjects])
  useEffect(() => { void loadEntries(selected, namespace) }, [selected, namespace, loadEntries])

  const call = async (url: string, init: RequestInit) => {
    setError('')
    const res = await fetch(`${API_BASE}${url}`, init).catch(() => null)
    if (!res) { setError('Backend not reachable.'); return false }
    if (!res.ok) { setError(await errorText(res)); return false }
    return true
  }

  const reload = () => { void loadEntries(selected, namespace); void loadSubjects() }

  const save = async (ns: string, key: string, text: string) => {
    if (selected === null) return false
    const ok = await call('/api/memory/store/entries', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject: selected, namespace: ns, key, value: parseValue(text) }),
    })
    if (ok) reload()
    return ok
  }

  const remove = async (e: StoreEntry) => {
    if (selected === null) return
    const q = new URLSearchParams({ subject: selected, namespace: e.namespace, key: e.key })
    if (await call(`/api/memory/store/entries?${q}`, { method: 'DELETE' })) reload()
  }

  const current = subjects.find((s) => s.subject === selected)

  return (
    <div className="ops-panel">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left"><span className="ops-panel-title">Key-value store</span></div>
        <div className="ops-toolbar-right">
          <button type="button" className="ops-refresh-btn" onClick={loadSubjects}>↻ Refresh</button>
        </div>
      </div>

      <div className="apikeys-body">
        <div className="apikeys-intro">
          Values agents saved with the Key-Value Store tool — per end user, or shared across the project. Edit a value
          as JSON (plain text is saved as a string); an edited entry keeps its expiry. Forgetting a user under
          Long-term also deletes their entries here.
        </div>

        {error && <div className="apikeys-error" role="alert">{error}</div>}

        <div className="ltm-layout">
          <div className="ltm-users" role="list" aria-label="Users">
            {subjects.length === 0 && <div className="ops-empty">Nothing stored yet.</div>}
            {subjects.map((s) => (
              <button key={s.subject || '(shared)'} type="button" role="listitem"
                className={`ltm-user${s.subject === selected ? ' ltm-user--active' : ''}`}
                onClick={() => { setSelected(s.subject); setNamespace(''); setEditing(null) }}>
                <span className="ltm-user-name">{s.subject || SHARED}</span>
                <span className="ltm-user-meta">{s.entries} entr{s.entries === 1 ? 'y' : 'ies'}</span>
              </button>
            ))}
          </div>

          {selected !== null && (
            <div className="ltm-facts">
              <div className="ltm-facts-head">
                <strong>{selected || SHARED}</strong>
                <select className="ops-select" aria-label="Namespace" value={namespace}
                  onChange={(e) => setNamespace(e.target.value)}>
                  <option value="">All namespaces</option>
                  {current?.namespaces.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </div>
              <div className="ops-list">
                {entries.map((e) => {
                  const id = `${e.namespace}/${e.key}`
                  const isEditing = editing?.namespace === e.namespace && editing.key === e.key
                  return (
                    <div key={id} className="ops-pipeline-row kv-row" title={`Updated ${fmt(e.updated_at)}`}>
                      <span className="kv-key"><span className="ltm-fact-meta kv-ns">{e.namespace}</span>{e.key}</span>
                      {isEditing ? (
                        <textarea className="ops-select kv-editor" aria-label={`Value of ${id}`} value={editing.text}
                          onChange={(ev) => setEditing({ ...editing, text: ev.target.value })} />
                      ) : (
                        <code className="ltm-fact kv-value">{show(e.value)}</code>
                      )}
                      <span className="ltm-fact-meta">expires {fmt(e.expires_at)}</span>
                      {isEditing ? (
                        <>
                          <button type="button" className="ops-link-btn"
                            onClick={async () => { if (await save(e.namespace, e.key, editing.text)) setEditing(null) }}>Save</button>
                          <button type="button" className="ops-link-btn" onClick={() => setEditing(null)}>Cancel</button>
                        </>
                      ) : (
                        <>
                          <button type="button" className="ops-link-btn" aria-label={`Edit ${id}`}
                            onClick={() => setEditing({ namespace: e.namespace, key: e.key, text: JSON.stringify(e.value, null, 2) })}>
                            Edit
                          </button>
                          <button type="button" className="ops-link-btn" aria-label={`Delete ${id}`} onClick={() => remove(e)}>
                            Delete
                          </button>
                        </>
                      )}
                    </div>
                  )
                })}
              </div>
              <form className="apikeys-form" onSubmit={async (ev) => {
                ev.preventDefault()
                if (await save(draft.namespace.trim(), draft.key.trim(), draft.value)) setDraft({ ...draft, key: '', value: '' })
              }}>
                <input type="text" className="ops-select kv-ns-input" aria-label="New entry namespace" placeholder="namespace"
                  value={draft.namespace} maxLength={128} onChange={(ev) => setDraft({ ...draft, namespace: ev.target.value })} />
                <input type="text" className="ops-select kv-key-input" aria-label="New entry key" placeholder="key"
                  value={draft.key} maxLength={200} onChange={(ev) => setDraft({ ...draft, key: ev.target.value })} />
                <input type="text" className="ops-select ltm-add" aria-label="New entry value" placeholder='value, e.g. {"units": "metric"}'
                  value={draft.value} onChange={(ev) => setDraft({ ...draft, value: ev.target.value })} />
                <button type="submit" className="ops-refresh-btn"
                  disabled={!draft.namespace.trim() || !draft.key.trim() || !draft.value.trim()}>Add</button>
              </form>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
