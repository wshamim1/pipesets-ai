import { useState, useEffect, useCallback, useMemo } from 'react'
import { API_BASE, PUBLIC_API_BASE } from '../../types'

interface ApiKey {
  id: string
  name: string
  key_prefix: string
  project_id: string
  created_by: string
  scopes: string[]
  rate_limit_rpm: number
  request_count: number
  created_at: string
  last_used_at: string | null
  expires_at: string | null
  revoked_at: string | null
  active: boolean
}

// Returned once by POST /api/api-keys — the only time the plaintext exists outside the caller
interface CreatedKey extends ApiKey {
  key: string
}

const SCOPES: { value: string; label: string; desc: string; byDefault: boolean }[] = [
  { value: 'apps:read',    label: 'Read',    desc: 'List and inspect published apps', byDefault: true },
  { value: 'apps:run',     label: 'Run',     desc: 'Run published apps', byDefault: true },
  { value: 'apps:write',   label: 'Write drafts', desc: 'MCP: create apps and edit drafts — never what is live', byDefault: false },
  { value: 'apps:publish', label: 'Publish', desc: 'MCP: put a draft live; its eval gate must pass, no override', byDefault: false },
  { value: 'tools:read',    label: 'Tools: read',    desc: 'SDK: list custom tools and their versions', byDefault: false },
  { value: 'tools:write',   label: 'Tools: deploy',  desc: 'SDK / CI: deploy custom tools and roll them back', byDefault: false },
  { value: 'tools:execute', label: 'Tools: run',     desc: 'SDK: test-run custom tools in the server sandbox', byDefault: false },
]

const EXPIRY_OPTIONS: { value: string; label: string }[] = [
  { value: '',    label: 'Never expires' },
  { value: '30',  label: '30 days' },
  { value: '90',  label: '90 days' },
  { value: '365', label: '1 year' },
]

// Backend timestamps are naive UTC ISO strings
const toDate = (iso: string) => new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))
const fmt = (iso: string | null) => (iso ? toDate(iso).toLocaleString() : '—')
const fmtShort = (iso: string | null) =>
  iso ? toDate(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'

function keyState(k: ApiKey): 'active' | 'revoked' | 'expired' {
  if (k.revoked_at) return 'revoked'
  return k.active ? 'active' : 'expired'
}

async function errorText(res: Response): Promise<string> {
  if (res.status === 403) return 'You need the api_keys:admin permission in this project (tenant owners have it).'
  try {
    const body = await res.json()
    return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
  } catch {
    return res.statusText
  }
}

export function ApiKeysPanel() {
  const [keys, setKeys] = useState<ApiKey[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showInactive, setShowInactive] = useState(false)

  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<string[]>(SCOPES.filter((s) => s.byDefault).map((s) => s.value))
  const [rpm, setRpm] = useState('60')
  const [expiry, setExpiry] = useState('')
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<CreatedKey | null>(null)
  const [copied, setCopied] = useState<'key' | 'curl' | 'mcp' | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/api-keys`)
      if (!res.ok) throw new Error(await errorText(res))
      setKeys(await res.json())
      setError(null)
    } catch (e) {
      setError(`Failed to load API keys: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const activeCount = keys.filter((k) => k.active).length
  const visible = useMemo(() => (showInactive ? keys : keys.filter((k) => k.active)), [keys, showInactive])

  const toggleScope = (scope: string) =>
    setScopes((prev) => (prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]))

  const create = async () => {
    const rpmNum = parseInt(rpm, 10)
    if (!name.trim()) { setError('Give the key a name so you can tell it apart later.'); return }
    if (scopes.length === 0) { setError('Select at least one scope.'); return }
    if (Number.isNaN(rpmNum) || rpmNum < 0) { setError('Rate limit must be 0 (unlimited) or more.'); return }
    setCreating(true)
    try {
      const res = await fetch(`${API_BASE}/api/api-keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          scopes,
          rate_limit_rpm: rpmNum,
          expires_in_days: expiry ? parseInt(expiry, 10) : null,
        }),
      })
      if (!res.ok) throw new Error(await errorText(res))
      setCreated(await res.json())
      setCopied(null)
      setName('')
      setError(null)
      load()
    } catch (e) {
      setError(`Create failed: ${(e as Error).message}`)
    } finally {
      setCreating(false)
    }
  }

  const revoke = async (k: ApiKey) => {
    if (!window.confirm(`Revoke "${k.name}" (${k.key_prefix}…)?\n\nAnything using this key stops working immediately. This cannot be undone.`)) return
    const res = await fetch(`${API_BASE}/api/api-keys/${encodeURIComponent(k.id)}`, { method: 'DELETE' })
    if (!res.ok) { setError(`Revoke failed: ${await errorText(res)}`); return }
    if (created?.id === k.id) setCreated(null)
    load()
  }

  const copy = (text: string, what: 'key' | 'curl' | 'mcp') => {
    navigator.clipboard.writeText(text).then(() => setCopied(what)).catch(() => setError('Copy failed — select the text and copy it manually.'))
  }

  const curlExample = created
    ? `curl -N ${PUBLIC_API_BASE}/v1/apps \\\n  -H "Authorization: Bearer ${created.key}"`
    : ''
  // The same key works as a remote MCP server (Claude Code shown; other clients take the URL + header)
  const mcpExample = created
    ? `claude mcp add --transport http pipesets ${PUBLIC_API_BASE}/v1/mcp \\\n  --header "Authorization: Bearer ${created.key}"`
    : ''

  return (
    <div className="ops-panel">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">API Keys</span>
          <span className="ops-count-badge">{activeCount} active</span>
          {keys.length > activeCount && (
            <span className="ops-count-badge">{keys.length - activeCount} revoked / expired</span>
          )}
        </div>
        <div className="ops-toolbar-right">
          <label className="ops-follow">
            <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> Show revoked
          </label>
          <button type="button" className="ops-refresh-btn" onClick={load} disabled={loading}>
            {loading ? '…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      <div className="apikeys-body">
        <div className="apikeys-intro">
          Keys authenticate external callers on the public <code>/v1</code> API, and MCP clients on
          {' '}<code>/v1/mcp</code>. A key acts as the user who created it in this project, so it can never reach
          more than you can.
        </div>

        {error && <div className="apikeys-error" role="alert">{error}</div>}

        {created && (
          <div className="apikeys-reveal" role="status">
            <div className="apikeys-reveal-title">
              🔑 “{created.name}” created — copy the key now. It will not be shown again.
            </div>
            <div className="apikeys-secret-row">
              <code className="apikeys-secret">{created.key}</code>
              <button type="button" className="ops-refresh-btn" onClick={() => copy(created.key, 'key')}>
                {copied === 'key' ? '✓ Copied' : 'Copy key'}
              </button>
            </div>
            <div className="apikeys-reveal-label">Try it:</div>
            <div className="apikeys-secret-row">
              <pre className="apikeys-snippet">{curlExample}</pre>
              <button type="button" className="ops-refresh-btn" onClick={() => copy(curlExample, 'curl')}>
                {copied === 'curl' ? '✓ Copied' : 'Copy'}
              </button>
            </div>
            <div className="apikeys-reveal-label">Use it from an MCP client (Claude Code, Claude Desktop, Cursor…):</div>
            <div className="apikeys-secret-row">
              <pre className="apikeys-snippet">{mcpExample}</pre>
              <button type="button" className="ops-refresh-btn" onClick={() => copy(mcpExample, 'mcp')}>
                {copied === 'mcp' ? '✓ Copied' : 'Copy'}
              </button>
            </div>
            <button type="button" className="ops-link-btn" onClick={() => setCreated(null)}>
              I’ve stored it — dismiss
            </button>
          </div>
        )}

        <div className="cost-card">
          <div className="cost-card-title">Create a key</div>
          <div className="apikeys-form">
            <input
              type="text" className="ops-select apikeys-name" placeholder="Name, e.g. Acme production"
              value={name} maxLength={100}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && create()}
            />
            {SCOPES.map((s) => (
              <label key={s.value} className="apikeys-scope" title={s.desc}>
                <input type="checkbox" checked={scopes.includes(s.value)} onChange={() => toggleScope(s.value)} />
                {s.label}
              </label>
            ))}
            <label className="apikeys-inline">
              <input
                type="number" min="0" className="ops-select apikeys-rpm"
                value={rpm} onChange={(e) => setRpm(e.target.value)}
              />
              req/min
            </label>
            <select className="ops-select" value={expiry} onChange={(e) => setExpiry(e.target.value)}>
              {EXPIRY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <button type="button" className="ops-refresh-btn" onClick={create} disabled={creating}>
              {creating ? '…' : 'Create key'}
            </button>
          </div>
          <div className="apikeys-hint">Rate limit 0 = unlimited. A key with only “Run” can run apps by id but cannot list them.</div>
        </div>

        <div className="apikeys-table">
        {visible.length > 0 && (
          <div className="ops-table-header">
            <span className="apikeys-col-name">Name</span>
            <span className="apikeys-col-key">Key</span>
            <span className="apikeys-col-scopes">Scopes</span>
            <span className="apikeys-col-num">Limit</span>
            <span className="apikeys-col-num">Requests</span>
            <span className="apikeys-col-date">Last used</span>
            <span className="apikeys-col-date">Expires</span>
            <span className="apikeys-col-status">Status</span>
            <span className="apikeys-col-actions" />
          </div>
        )}
        <div className="ops-list">
          {visible.length === 0 && !loading && (
            <div className="ops-empty">
              {keys.length === 0 ? 'No API keys yet. Create one above to call the /v1 API.' : 'No active keys. Tick “Show revoked” to see the others.'}
            </div>
          )}
          {visible.map((k) => {
            const state = keyState(k)
            return (
              <div key={k.id} className={`ops-pipeline-row${state !== 'active' ? ' apikeys-row--inactive' : ''}`}>
                <span className="apikeys-col-name" title={`Created ${fmt(k.created_at)} by ${k.created_by}`}>{k.name}</span>
                <span className="apikeys-col-key"><code>{k.key_prefix}…</code></span>
                <span className="apikeys-col-scopes">
                  {k.scopes.map((s) => <span key={s} className="apikeys-scope-chip">{s.replace('apps:', '')}</span>)}
                </span>
                <span className="apikeys-col-num">{k.rate_limit_rpm ? `${k.rate_limit_rpm}/min` : '∞'}</span>
                <span className="apikeys-col-num">{k.request_count.toLocaleString()}</span>
                <span className="apikeys-col-date" title={fmt(k.last_used_at)}>{k.last_used_at ? fmtShort(k.last_used_at) : 'never'}</span>
                <span className="apikeys-col-date" title={fmt(k.expires_at)}>{k.expires_at ? fmtShort(k.expires_at) : 'never'}</span>
                <span className="apikeys-col-status">
                  <span
                    className={`ops-status-pill apikeys-pill--${state}`}
                    title={k.revoked_at ? `Revoked ${fmt(k.revoked_at)}` : undefined}
                  >{state}</span>
                </span>
                <span className="apikeys-col-actions">
                  {state === 'active' && (
                    <button type="button" className="ops-danger-btn ops-danger-btn--sm" onClick={() => revoke(k)}>Revoke</button>
                  )}
                </span>
              </div>
            )
          })}
        </div>
        </div>
      </div>
    </div>
  )
}
