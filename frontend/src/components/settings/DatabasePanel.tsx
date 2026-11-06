import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../../types'

export interface DatabaseInfo {
  backend: string
  driver: string
  host: string
  port: number | null
  database: string
  server_version: string
  size_bytes: number | null
  schema: { current: string | null; head: string; pending: { revision: string; description: string }[] }
}

export interface SetupState {
  can_configure: boolean
  reasons: string[]
  source: 'default' | 'env_file' | 'environment'
  env_file: string
  pending_restart: string | null
}

interface PgForm {
  host: string
  port: string
  database: string
  user: string
  password: string
  sslmode: string
}

const EMPTY_FORM: PgForm = { host: '', port: '5432', database: 'pipesets', user: '', password: '', sslmode: 'prefer' }
const SSL_MODES = ['disable', 'prefer', 'require', 'verify-full']

const NAMES: Record<string, string> = { sqlite: 'SQLite', postgresql: 'PostgreSQL', mysql: 'MySQL', mssql: 'SQL Server' }
const COPY_CMD = 'python manage.py db copy --to postgresql+psycopg2://USER:PASSWORD@HOST:5432/pipesets'

export function formatBytes(n: number | null): string {
  if (n == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v < 10 && i ? v.toFixed(1) : Math.round(v)} ${units[i]}`
}

function Command({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="apikeys-secret-row">
      <pre className="apikeys-snippet dbinfo-cmd">{text}</pre>
      <button type="button" className="ops-refresh-btn"
        onClick={() => navigator.clipboard.writeText(text).then(() => setCopied(true)).catch(() => setCopied(false))}>
        {copied ? '✓ Copied' : 'Copy'}
      </button>
    </div>
  )
}

async function errorText(r: Response): Promise<string> {
  const body = await r.json().catch(() => ({}))
  return typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`
}

/**
 * "Use PostgreSQL" on a fresh install: test a connection, then copy this (nearly empty) database
 * into it and save DATABASE_URL for the next start (services/db_setup.py on the backend).
 */
function PostgresSetup({ onSaved }: { onSaved: () => void }) {
  const [form, setForm] = useState<PgForm>(EMPTY_FORM)
  const [tested, setTested] = useState<{ ok: boolean; message: string; for: string } | null>(null)
  const [busy, setBusy] = useState<'test' | 'apply' | null>(null)
  const [error, setError] = useState('')
  const key = JSON.stringify(form)
  const body = () => JSON.stringify({ ...form, port: Number(form.port) || 5432 })
  const ready = form.host.trim() && form.database.trim() && form.user.trim()
  const testedOk = tested?.ok && tested.for === key
  const set = (k: keyof PgForm) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })

  const test = async () => {
    setBusy('test')
    setError('')
    try {
      const r = await fetch(`${API_BASE}/api/system/database/test`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body() })
      if (!r.ok) { setError(await errorText(r)); return }
      const d = await r.json()
      setTested({ ok: d.ok, message: d.message, for: key })
    } catch {
      setError('Backend not reachable.')
    } finally {
      setBusy(null)
    }
  }

  const apply = async () => {
    if (!window.confirm(`Switch this server to PostgreSQL at ${form.host}?\n\nEverything here so far is copied into it, and the server uses it after its next restart.`)) return
    setBusy('apply')
    setError('')
    try {
      const r = await fetch(`${API_BASE}/api/system/database/setup`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body() })
      if (!r.ok) { setError(await errorText(r)); return }
      setForm(EMPTY_FORM)
      setTested(null)
      onSaved()
    } catch {
      setError('Backend not reachable.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <div className="dbsetup-form">
        <label className="dbsetup-field dbsetup-field--wide">Host
          <input className="ops-select" value={form.host} onChange={set('host')} placeholder="db.example.com" />
        </label>
        <label className="dbsetup-field">Port
          <input className="ops-select" value={form.port} onChange={set('port')} inputMode="numeric" />
        </label>
        <label className="dbsetup-field">Database
          <input className="ops-select" value={form.database} onChange={set('database')} />
        </label>
        <label className="dbsetup-field">User
          <input className="ops-select" value={form.user} onChange={set('user')} autoComplete="off" />
        </label>
        <label className="dbsetup-field">Password
          <input className="ops-select" type="password" value={form.password} onChange={set('password')} autoComplete="new-password" />
        </label>
        <label className="dbsetup-field">SSL
          <select className="ops-select" value={form.sslmode} onChange={set('sslmode')}>
            {SSL_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
      </div>
      <div className="card-actions-row dbsetup-actions">
        <button type="button" className="ops-refresh-btn" disabled={!ready || busy !== null} onClick={test}>
          {busy === 'test' ? 'Testing…' : 'Test connection'}
        </button>
        <button type="button" className="ops-refresh-btn dbsetup-apply" disabled={!testedOk || busy !== null} onClick={apply}
          title={testedOk ? undefined : 'Test the connection first'}>
          {busy === 'apply' ? 'Copying…' : 'Switch to this database'}
        </button>
        {tested && tested.for === key && (
          <span className={tested.ok ? 'dbinfo-ok' : 'dbinfo-warn'} role="status">{tested.ok ? '✓ ' : '✗ '}{tested.message}</span>
        )}
      </div>
      {error && <div className="apikeys-error" role="alert">{error}</div>}
    </>
  )
}

/**
 * Settings → Database: which database this server uses, whether its schema is current, and how to
 * move to another one. The server's DATABASE_URL decides; on a fresh install a server admin can
 * set it here (see DEPLOYMENT.md).
 */
export function DatabasePanel() {
  const [info, setInfo] = useState<DatabaseInfo | null>(null)
  const [setup, setSetup] = useState<SetupState | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const r = await fetch(`${API_BASE}/api/system/database`)
      if (r.status === 403) setError('Only a server admin can see this. The first account on the server is one; others are added with `python manage.py server-admin EMAIL`.')
      else if (!r.ok) setError(`Couldn't read the database details (HTTP ${r.status}).`)
      else {
        setInfo(await r.json())
        // Setup is extra: if it can't be read, the rest of the page still stands
        const s = await fetch(`${API_BASE}/api/system/database/setup`).catch(() => null)
        setSetup(s?.ok ? await s.json() : null)
      }
    } catch {
      setError('Backend not reachable.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const sqlite = info?.backend === 'sqlite'
  const where = !info ? '' : sqlite ? info.database : `${info.host}${info.port ? `:${info.port}` : ''} / ${info.database}`

  return (
    <div className="ops-panel">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">Database</span>
          {info && <span className="ops-count-badge">{NAMES[info.backend] ?? info.backend}</span>}
        </div>
        <div className="ops-toolbar-right">
          <button type="button" className="ops-refresh-btn" onClick={load} disabled={loading}>
            {loading ? 'Loading…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      <div className="apikeys-body">
        <div className="apikeys-intro">
          Pipelines, runs, users, secrets and the audit log are all stored here. The server picks the database
          with <code>DATABASE_URL</code> when it starts — empty means SQLite — so it can't be changed from this page.
        </div>
        {error && <div className="apikeys-error" role="alert">{error}</div>}
        {setup?.pending_restart && (
          <div className="apikeys-reveal" role="status">
            <div className="apikeys-reveal-title">Restart to finish</div>
            <div className="apikeys-intro">
              Saved in <code>{setup.env_file}</code>: after its next restart this server uses{' '}
              <code>{setup.pending_restart}</code>. Restart the backend — or quit and reopen the desktop app.
            </div>
          </div>
        )}

        {info && (
          <>
            <div className="cost-card">
              <div className="cost-card-title">Connection</div>
              <dl className="dbinfo-grid">
                <dt>Type</dt>
                <dd>{NAMES[info.backend] ?? info.backend}{info.server_version && ` ${info.server_version}`}</dd>
                <dt>{sqlite ? 'File' : 'Server'}</dt>
                <dd><code>{where || '—'}</code></dd>
                <dt>Driver</dt>
                <dd>{info.driver}</dd>
                <dt>Size</dt>
                <dd>{formatBytes(info.size_bytes)}</dd>
              </dl>
              {sqlite && (
                <div className="apikeys-hint">
                  SQLite is one file on this server: fine for a desktop install or a trial, but it serves one
                  backend at a time. Use PostgreSQL for a shared or production install.
                </div>
              )}
            </div>

            <div className="cost-card">
              <div className="cost-card-title">Schema</div>
              {info.schema.pending.length === 0 ? (
                <div className="dbinfo-ok">✓ Up to date — revision <code>{info.schema.head}</code></div>
              ) : (
                <>
                  <div className="dbinfo-warn">
                    ⚠ {info.schema.pending.length} migration{info.schema.pending.length > 1 ? 's' : ''} pending — the
                    database is at <code>{info.schema.current ?? 'no revision'}</code>, this version of the app
                    needs <code>{info.schema.head}</code>.
                  </div>
                  <ul className="dbinfo-pending">
                    {info.schema.pending.map((p) => (
                      <li key={p.revision}><code>{p.revision}</code> {p.description}</li>
                    ))}
                  </ul>
                  <div className="apikeys-hint">The backend applies them when it starts, or run on the server:</div>
                  <Command text="python manage.py db setup" />
                </>
              )}
            </div>

            {setup && !setup.pending_restart && (
              <div className="cost-card">
                <div className="cost-card-title">Use PostgreSQL</div>
                {setup.can_configure ? (
                  <>
                    <div className="apikeys-hint dbsetup-intro">
                      Before you build pipelines, point this server at a PostgreSQL database. What's here so far
                      — your account and workspace — is copied into it, and the server switches at its next restart.
                    </div>
                    <PostgresSetup onSaved={load} />
                  </>
                ) : (
                  <ul className="dbinfo-pending">
                    {setup.reasons.map((r) => <li key={r}>{r}</li>)}
                  </ul>
                )}
              </div>
            )}

            <div className="cost-card">
              <div className="cost-card-title">Move to another database</div>
              <ol className="dbinfo-steps">
                <li>Create an empty PostgreSQL database and stop the backend.</li>
                <li>On the server, from <code>backend/</code>, copy everything into it — one transaction, row
                  counts checked, nothing kept if it fails:
                  <Command text={COPY_CMD} />
                </li>
                <li>Set <code>DATABASE_URL</code> to the new database and start the backend, with the same master
                  key — secrets are copied still encrypted.</li>
              </ol>
              <div className="apikeys-hint">The old database is left as it was. Details in DEPLOYMENT.md.</div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
