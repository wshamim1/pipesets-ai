/**
 * LabView — Research Lab environment management (Docker / Podman / Kubernetes)
 *
 * Tabs:
 *   🧱 Services    — databases, vector stores, search, messaging (Kafka, RabbitMQ, ...) in Docker/Podman
 *   📄 PDF Studio  — generate test PDFs (plain, report, bio, invoice)
 *   🌱 Data Seeder — pick a preset dataset and seed it in one click
 *   🦙 Ollama      — install, browse and delete local Ollama models
 *   🦙 llama.cpp   — install llama-server, start / stop servers, tail their logs
 */

import { useState, useEffect, useRef } from 'react'
import { API_BASE } from '../types'

// ── Types ─────────────────────────────────────────────────────────────────────

type LabTab = 'services' | 'pdf' | 'seeder' | 'ollama' | 'llamacpp'

interface LabStatus {
  docker_available: boolean
  podman_available: boolean
  kubernetes_available?: boolean
  runtime_problems?: Record<string, string>
  reportlab_available: boolean
  postgres_container: Record<string, any> | null
  postgres_running: boolean
}

interface PgContainer {
  container_name: string
  container_id: string
  image: string
  port: number
  db_name: string
  db_user: string
  dsn: string
  runtime: string
  started_at: string
  ready: boolean
}

// ── helpers ───────────────────────────────────────────────────────────────────

function Badge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`lab-badge ${ok ? 'lab-badge--ok' : 'lab-badge--off'}`}>
      {ok ? '✓' : '✗'} {label}
    </span>
  )
}

function LogBox({ lines }: { lines: string[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { ref.current?.scrollTo(0, ref.current.scrollHeight) }, [lines])
  return (
    <div ref={ref} className="lab-log-box">
      {lines.length === 0
        ? <span className="lab-log-empty">No output yet.</span>
        : lines.map((l, i) => <div key={i} className={`lab-log-line${l.startsWith('❌') ? ' lab-log-error' : l.startsWith('✅') ? ' lab-log-ok' : l.startsWith('⚠') ? ' lab-log-warn' : ''}`}>{l}</div>)
      }
    </div>
  )
}

// ── Runtime picker (Auto / Podman / Docker / Kubernetes) ─────────────────────

const RUNTIME_OPTIONS: { id: string; icon: string; label: string; statusKey?: 'podman_available' | 'docker_available' | 'kubernetes_available'; key?: string }[] = [
  { id: 'auto',       icon: '✨', label: 'Auto' },
  { id: 'podman',     icon: '🦭', label: 'Podman',     statusKey: 'podman_available',     key: 'podman' },
  { id: 'docker',     icon: '🐳', label: 'Docker',     statusKey: 'docker_available',     key: 'docker' },
  { id: 'kubernetes', icon: '☸️', label: 'Kubernetes', statusKey: 'kubernetes_available', key: 'kubernetes' },
]

function RuntimePicker({ value, status, disabled, onChange }: {
  value: string
  status: LabStatus | null
  disabled?: boolean
  onChange: (runtime: string) => void
}) {
  const problem = status?.runtime_problems?.[value]
  return (
    <div className="lab-runtime">
      <label className="lab-label">Runtime</label>
      <div className="lab-runtime-options" role="radiogroup" aria-label="Container runtime">
        {RUNTIME_OPTIONS.map((o) => {
          const ok = o.statusKey ? status?.[o.statusKey] : undefined
          return (
            <button key={o.id} type="button" role="radio" aria-checked={value === o.id} disabled={disabled}
              className={`lab-runtime-btn ${value === o.id ? 'lab-runtime-btn--active' : ''}`}
              title={o.key ? (status?.runtime_problems?.[o.key] ?? 'Available') : 'Use the first available of Docker, Podman'}
              onClick={() => onChange(o.id)}>
              <span>{o.icon}</span> {o.label}
              {o.statusKey && status && <span className={`lab-runtime-dot ${ok ? 'lab-runtime-dot--on' : 'lab-runtime-dot--off'}`} />}
            </button>
          )
        })}
      </div>
      {problem && <div className="lab-runtime-warn">⚠ {problem}</div>}
      {value === 'kubernetes' && !problem && (
        <div className="lab-hint">Runs a pod in your current kubectl context and exposes it on localhost via <code>kubectl port-forward</code>.</div>
      )}
    </div>
  )
}

// ── Postgres Tab ──────────────────────────────────────────────────────────────

function PostgresTab({ status, onStatusRefresh }: { status: LabStatus | null; onStatusRefresh: () => void }) {
  const [cfg, setCfg] = useState({ container_name: 'lab-postgres', image: 'postgres:16-alpine', port: 5433, db_name: 'labdb', db_user: 'labuser', db_password: 'labpass', runtime: 'auto' })
  const [loading, setLoading] = useState<string | null>(null)
  const [log, setLog] = useState<string[]>([])
  const [sql, setSql] = useState('-- Write SQL here\nSELECT NOW() AS server_time;\n')
  const [sqlResult, setSqlResult] = useState<any[] | null>(null)

  const push = (line: string) => setLog((p) => [...p, line])

  const container = status?.postgres_container as PgContainer | null
  const isRunning = status?.postgres_running ?? false

  async function start() {
    setLoading('start')
    push(`⏳ Starting container '${cfg.container_name}' via ${cfg.runtime === 'auto' ? 'auto-detected runtime' : cfg.runtime}…`)
    try {
      const r = await fetch(`${API_BASE}/api/lab/postgres/start`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      })
      const d = await r.json()
      if (d.success) {
        push(`✅ Container started. DSN: ${d.dsn}`)
        push(d.ready ? '✅ Postgres is ready.' : '⚠ Postgres not yet ready — wait a few seconds and refresh.')
      } else {
        push(`❌ Failed: ${d.error}`)
      }
      onStatusRefresh()
    } catch (e: any) { push(`❌ Network error: ${e.message}`) }
    setLoading(null)
  }

  async function stop() {
    setLoading('stop')
    push('⏳ Stopping container…')
    try {
      const r = await fetch(`${API_BASE}/api/lab/postgres/stop`, { method: 'POST' })
      const d = await r.json()
      push(d.success ? '✅ Container stopped.' : `❌ ${d.error}`)
      onStatusRefresh()
    } catch (e: any) { push(`❌ Network error: ${e.message}`) }
    setLoading(null)
  }

  async function execSql() {
    setLoading('sql')
    setSqlResult(null)
    try {
      const r = await fetch(`${API_BASE}/api/lab/postgres/exec`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql }),
      })
      const d = await r.json()
      if (d.success) {
        setSqlResult(d.results)
        push(`✅ SQL executed — ${d.results.length} statement(s).`)
      } else {
        push(`❌ SQL error: ${d.error}`)
      }
    } catch (e: any) { push(`❌ Network error: ${e.message}`) }
    setLoading(null)
  }

  const field = (label: string, key: keyof typeof cfg, type: string = 'text', placeholder = '') => (
    <div className="lab-field" key={key}>
      <label className="lab-label">{label}</label>
      <input type={type} className="lab-input" placeholder={placeholder}
        value={String(cfg[key])} disabled={isRunning}
        onChange={(e) => setCfg((p) => ({ ...p, [key]: type === 'number' ? parseInt(e.target.value) || 0 : e.target.value }))}
      />
    </div>
  )

  return (
    <div className="lab-tab-body">
      {/* Status banner */}
      <div className={`lab-status-banner ${isRunning ? 'lab-status-banner--running' : 'lab-status-banner--stopped'}`}>
        <span className={`lab-status-dot ${isRunning ? 'lab-status-dot--on' : 'lab-status-dot--off'}`} />
        {isRunning
          ? <>Container <strong>{container?.container_name}</strong> running on port <strong>{container?.port}</strong> via <strong>{container?.runtime}</strong></>
          : 'No Postgres container running'}
        {isRunning && container?.dsn && (
          <code className="lab-dsn-pill">{container.dsn.replace(/:labpass@/, ':***@')}</code>
        )}
        <button type="button" className="lab-refresh-btn" onClick={onStatusRefresh}>↻ Refresh</button>
      </div>

      <div className="lab-two-col">
        {/* Left: config */}
        <div className="lab-card">
          <h4 className="lab-card-title">🐘 Container Configuration</h4>
          <div className="lab-fields-grid">
            {field('Container Name', 'container_name')}
            {field('Image', 'image', 'text', 'postgres:16-alpine')}
            {field('Host Port', 'port', 'number', '5433')}
            {field('Database', 'db_name')}
            {field('User', 'db_user')}
            {field('Password', 'db_password', 'password')}
          </div>
          <RuntimePicker value={cfg.runtime} status={status} disabled={isRunning}
            onChange={(runtime) => setCfg((p) => ({ ...p, runtime }))} />
          <div className="lab-card-actions">
            {!isRunning
              ? <button type="button" className="lab-btn lab-btn--primary" disabled={loading === 'start'} onClick={start}>
                  {loading === 'start' ? '⏳ Starting…' : '▶ Start Postgres'}
                </button>
              : <button type="button" className="lab-btn lab-btn--danger" disabled={loading === 'stop'} onClick={stop}>
                  {loading === 'stop' ? '⏳ Stopping…' : '⏹ Stop Container'}
                </button>
            }
          </div>
        </div>

        {/* Right: SQL editor */}
        <div className="lab-card">
          <h4 className="lab-card-title">⚡ SQL Console</h4>
          <textarea className="lab-sql-editor" value={sql} onChange={(e) => setSql(e.target.value)}
            placeholder="-- Write SQL here" spellCheck={false} />
          <button type="button" className="lab-btn lab-btn--primary" style={{ marginTop: 8 }}
            disabled={!isRunning || loading === 'sql'} onClick={execSql}>
            {loading === 'sql' ? '⏳ Running…' : '▶ Run SQL'}
          </button>
          {!isRunning && <div className="lab-hint">Start the container first to run SQL.</div>}

          {/* Results table */}
          {sqlResult && sqlResult.map((res, i) => (
            <div key={i} className="lab-result-block">
              <div className="lab-result-title">
                Statement {i + 1}: <code>{res.statement}…</code>
                {res.row_count !== undefined && <span className="lab-row-count">{res.row_count} row{res.row_count !== 1 ? 's' : ''}</span>}
                {res.rowcount !== undefined && <span className="lab-row-count">{res.rowcount} row{res.rowcount !== 1 ? 's' : ''} affected</span>}
              </div>
              {res.columns && res.rows && (
                <div className="lab-table-scroll">
                  <table className="lab-table">
                    <thead><tr>{res.columns.map((c: string) => <th key={c}>{c}</th>)}</tr></thead>
                    <tbody>{res.rows.map((row: any[], ri: number) => (
                      <tr key={ri}>{row.map((cell, ci) => <td key={ci}>{String(cell ?? 'NULL')}</td>)}</tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="lab-card" style={{ marginTop: 16 }}>
        <h4 className="lab-card-title">📋 Activity Log</h4>
        <LogBox lines={log} />
      </div>
    </div>
  )
}

// ── Services Tab (MySQL, MongoDB, Elasticsearch, ...) ─────────────────────────

interface ServiceSpec {
  category?: string
  label: string
  icon: string
  image: string
  host_port: number
  fields: string[]
  user?: string
  password?: string
  database?: string
  note?: string
  conn?: string
  datasets?: string[]
}

interface ServiceCategory {
  id: string
  label: string
  icon: string
}

interface ServiceContainer {
  container_name: string
  service: string
  image: string
  port: number
  runtime: string
  ready: boolean
  running: boolean
  conn: string
}

const POSTGRES_ID = 'postgres'
const POSTGRES_SPEC: ServiceSpec = {
  category: 'relational', label: 'Postgres', icon: '🐘', image: 'postgres:16-alpine',
  host_port: 5433, fields: [], note: 'SQL console + Data Seeder',
}

function ServicesTab({ status, onStatusRefresh }: { status: LabStatus | null; onStatusRefresh: () => void }) {
  const [catalog, setCatalog] = useState<Record<string, ServiceSpec>>({})
  const [categories, setCategories] = useState<ServiceCategory[]>([])
  // Groups start collapsed; only the selected service's group (Postgres → relational) is open
  const [expanded, setExpanded] = useState<Set<string>>(new Set([POSTGRES_SPEC.category!]))
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(POSTGRES_ID)
  const [seedChoice, setSeedChoice] = useState<Record<string, string>>({})
  const [cfg, setCfg] = useState({ container_name: '', image: '', port: 0, user: '', password: '', database: '', runtime: 'auto' })
  const [containers, setContainers] = useState<ServiceContainer[]>([])
  const [loading, setLoading] = useState<string | null>(null)
  const [log, setLog] = useState<string[]>([])
  const push = (line: string) => setLog((p) => [...p, line])

  async function fetchContainers() {
    try {
      const r = await fetch(`${API_BASE}/api/lab/services/status`)
      setContainers((await r.json()).containers ?? [])
    } catch { /* backend may not be running */ }
  }

  useEffect(() => {
    fetch(`${API_BASE}/api/lab/services/catalog`)
      .then((r) => r.json())
      .then((d) => { setCatalog(d.services ?? {}); setCategories(d.categories ?? []) })
      .catch(() => { /* backend may not be running */ })
    fetchContainers()
  }, [])

  const isPostgres = selected === POSTGRES_ID
  const spec = isPostgres ? undefined : catalog[selected]

  // Reset the form to the selected service's defaults
  useEffect(() => {
    if (!spec) return
    setCfg((p) => ({
      ...p, container_name: `lab-${selected}`, image: spec.image, port: spec.host_port,
      user: spec.user ?? '', password: spec.password ?? '', database: spec.database ?? '',
    }))
  }, [selected, spec])

  const running = containers.find((c) => c.container_name === cfg.container_name && c.running)

  // Sidebar: Postgres + catalog, filtered by category chip and search, grouped by category
  const allServices: [string, ServiceSpec][] = [[POSTGRES_ID, POSTGRES_SPEC], ...Object.entries(catalog)]
  const q = query.trim().toLowerCase()
  const visible = allServices.filter(([id, s]) => !q || `${id} ${s.label} ${s.image}`.toLowerCase().includes(q))
  const knownCats = new Set(categories.map((c) => c.id))
  const groups = [...categories, { id: 'other', label: 'Other', icon: '🧩' }]
    .map((c) => ({ ...c, items: visible.filter(([, s]) => (knownCats.has(s.category ?? '') ? s.category : 'other') === c.id) }))
    .filter((g) => g.items.length > 0)
  const toggleGroup = (id: string) => setExpanded((p) => {
    const n = new Set(p)
    n.has(id) ? n.delete(id) : n.add(id)
    return n
  })
  const isServiceRunning = (id: string) => id === POSTGRES_ID
    ? !!status?.postgres_running
    : containers.some((c) => c.service === id && c.running)
  const connPreview = spec?.conn
    ?.replace(/\{port\}/g, String(cfg.port)).replace(/\{user\}/g, cfg.user)
    .replace(/\{password\}/g, cfg.password ? '***' : '').replace(/\{database\}/g, cfg.database)
  const categoryOf = (id?: string) => categories.find((c) => c.id === id)

  async function start() {
    setLoading('start')
    push(`⏳ Starting ${spec?.label} ('${cfg.container_name}') — first run may need to pull the image…`)
    try {
      const r = await fetch(`${API_BASE}/api/lab/services/start`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ service: selected, ...cfg }),
      })
      const d = await r.json()
      if (d.success) {
        push(`✅ ${d.message}`)
        push(`🔗 ${d.conn}`)
        if (!d.ready) push('⚠ Not ready yet — use "Logs" and refresh in a few seconds.')
      } else {
        push(`❌ Failed: ${d.error}`)
      }
      fetchContainers()
    } catch (e: any) { push(`❌ Network error: ${e.message}`) }
    setLoading(null)
  }

  async function stop(name: string) {
    setLoading(`stop:${name}`)
    try {
      const r = await fetch(`${API_BASE}/api/lab/services/stop`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ container_name: name }),
      })
      const d = await r.json()
      push(d.success ? `✅ ${d.message}` : `❌ ${d.error}`)
      fetchContainers()
    } catch (e: any) { push(`❌ Network error: ${e.message}`) }
    setLoading(null)
  }

  async function seedService(c: ServiceContainer) {
    const dataset = seedChoice[c.container_name] ?? catalog[c.service]?.datasets?.[0]
    if (!dataset) return
    setLoading(`seed:${c.container_name}`)
    push(`⏳ Seeding '${dataset}' into ${c.container_name}…`)
    try {
      const r = await fetch(`${API_BASE}/api/lab/services/seed`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ container_name: c.container_name, dataset }),
      })
      const d = await r.json()
      push(d.success ? `✅ ${d.message}` : `❌ ${d.error}`)
    } catch (e: any) { push(`❌ Network error: ${e.message}`) }
    setLoading(null)
  }

  async function showLogs(name: string) {
    try {
      const r = await fetch(`${API_BASE}/api/lab/services/logs?container_name=${encodeURIComponent(name)}&tail=40`)
      const d = await r.json()
      if (d.success) {
        push(`📜 Logs for '${name}':`)
        String(d.logs).split('\n').forEach(push)
      } else {
        push(`❌ ${d.error}`)
      }
    } catch (e: any) { push(`❌ Network error: ${e.message}`) }
  }

  const textField = (label: string, key: 'container_name' | 'image' | 'user' | 'password' | 'database', type = 'text') => (
    <div className="lab-field" key={key}>
      <label className="lab-label">{label}</label>
      <input type={type} className="lab-input" value={cfg[key]} disabled={!!running}
        onChange={(e) => setCfg((p) => ({ ...p, [key]: e.target.value }))} />
    </div>
  )

  return (
    <div className="lab-tab-body">
      <div className="lab-services-layout">
      {/* Left: services */}
      <div className="lab-card lab-services-sidebar">
        <h4 className="lab-card-title">🧱 Services <span className="lab-row-count">{allServices.length}</span></h4>
        <input type="search" className="lab-input lab-service-search" placeholder="Search services…"
          value={query} onChange={(e) => setQuery(e.target.value)} />
        <div className="lab-service-list">
          {groups.map((g) => {
            const open = !!q || expanded.has(g.id)
            const runningCount = g.items.filter(([id]) => isServiceRunning(id)).length
            return (
              <div key={g.id} className="lab-service-group">
                <button type="button" className="lab-service-group-title" aria-expanded={open}
                  onClick={() => toggleGroup(g.id)}>
                  <span className={`lab-service-group-chevron ${open ? 'lab-service-group-chevron--open' : ''}`}>▸</span>
                  <span className="lab-service-group-name">{g.label}</span>
                  {runningCount > 0 && <span className="lab-status-dot lab-status-dot--on" title={`${runningCount} running`} />}
                  <span className="lab-service-group-count">{g.items.length}</span>
                </button>
                {open && g.items.map(([id, s]) => (
                  <button key={id} type="button"
                    className={`lab-service-item ${selected === id ? 'lab-service-item--selected' : ''}`}
                    onClick={() => setSelected(id)} title={s.image}>
                    <span className="lab-service-item-icon">{s.icon}</span>
                    <span className="lab-service-item-text">
                      <span className="lab-service-item-label">{s.label}</span>
                      <span className="lab-service-item-image">{s.image}</span>
                    </span>
                    {isServiceRunning(id) && <span className="lab-status-dot lab-status-dot--on" title="Running" />}
                  </button>
                ))}
              </div>
            )
          })}
          {groups.length === 0 && <div className="lab-hint">No services match “{query}”.</div>}
        </div>
        {Object.keys(catalog).length === 0 && <div className="lab-hint">Could not load the other services — is the backend running (and restarted since the last update)?</div>}
      </div>

      {/* Right: configuration */}
      <div className="lab-services-main">
      {isPostgres && <PostgresTab status={status} onStatusRefresh={onStatusRefresh} />}

      {spec && (
        <div className="lab-card">
          <h4 className="lab-card-title">
            {spec.icon} {spec.label} Configuration
            {categoryOf(spec.category) && <span className="lab-cat-tag">{categoryOf(spec.category)!.label}</span>}
          </h4>
          {spec.note && <p className="lab-hint">{spec.note}</p>}
          <div className="lab-fields-grid">
            {textField('Container Name', 'container_name')}
            {textField('Image', 'image')}
            <div className="lab-field">
              <label className="lab-label">Host Port</label>
              <input type="number" className="lab-input" value={cfg.port} disabled={!!running}
                onChange={(e) => setCfg((p) => ({ ...p, port: parseInt(e.target.value) || 0 }))} />
            </div>
            {spec.fields.includes('user') && textField('User', 'user')}
            {spec.fields.includes('password') && textField('Password', 'password', 'password')}
            {spec.fields.includes('database') && textField('Database', 'database')}
          </div>
          {connPreview && (
            <div className="lab-field">
              <label className="lab-label">Connect with</label>
              <code className="lab-dsn-pill lab-conn-preview">{connPreview}</code>
            </div>
          )}
          <RuntimePicker value={cfg.runtime} status={status} disabled={!!running}
            onChange={(runtime) => setCfg((p) => ({ ...p, runtime }))} />
          <div className="lab-card-actions">
            <button type="button" className="lab-btn lab-btn--primary" disabled={loading === 'start' || !!running} onClick={start}>
              {loading === 'start' ? '⏳ Starting…' : `▶ Start ${spec.label}`}
            </button>
          </div>
        </div>
      )}

      {!isPostgres && <div className="lab-card" style={{ marginTop: 16 }}>
        <h4 className="lab-card-title">
          🏃 Running Services
          <button type="button" className="lab-refresh-btn" style={{ marginLeft: 8 }} onClick={fetchContainers}>↻ Refresh</button>
        </h4>
        {containers.length === 0
          ? <div className="lab-hint">No service containers started from this session.</div>
          : containers.map((c) => (
            <div key={c.container_name} className="lab-result-block">
              <div className="lab-result-title">
                <span className={`lab-status-dot ${c.running ? 'lab-status-dot--on' : 'lab-status-dot--off'}`} />{' '}
                <strong>{c.container_name}</strong> ({c.image}) — port {c.port} via {c.runtime}
                {!c.ready && <span className="lab-row-count">not ready</span>}
              </div>
              <code className="lab-dsn-pill">{c.conn}</code>
              <div className="lab-card-actions">
                {(catalog[c.service]?.datasets?.length ?? 0) > 0 && c.running && (
                  <>
                    <select className="lab-input" style={{ width: 'auto' }}
                      value={seedChoice[c.container_name] ?? catalog[c.service]?.datasets?.[0]}
                      onChange={(e) => setSeedChoice((p) => ({ ...p, [c.container_name]: e.target.value }))}>
                      {catalog[c.service]?.datasets?.map((ds) => <option key={ds} value={ds}>{ds}</option>)}
                    </select>
                    <button type="button" className="lab-btn" disabled={loading === `seed:${c.container_name}`}
                      onClick={() => seedService(c)}>
                      {loading === `seed:${c.container_name}` ? '⏳ Seeding…' : '🌱 Seed'}
                    </button>
                  </>
                )}
                <button type="button" className="lab-btn" onClick={() => showLogs(c.container_name)}>📜 Logs</button>
                <button type="button" className="lab-btn lab-btn--danger" disabled={loading === `stop:${c.container_name}`}
                  onClick={() => stop(c.container_name)}>
                  {loading === `stop:${c.container_name}` ? '⏳ Stopping…' : '⏹ Stop'}
                </button>
              </div>
            </div>
          ))}
      </div>}

      {!isPostgres && <div className="lab-card" style={{ marginTop: 16 }}>
        <h4 className="lab-card-title">📋 Activity Log</h4>
        <LogBox lines={log} />
      </div>}
      </div>
      </div>
    </div>
  )
}

// ── Data Seeder Tab ───────────────────────────────────────────────────────────

const DATASETS = [
  { id: 'ecommerce', icon: '🛒', label: 'E-Commerce', desc: 'customers, products, orders, order_items — 5 customers, 7 products, 5 orders' },
  { id: 'hr',        icon: '👥', label: 'HR / Employees', desc: 'departments, employees, performance_reviews — 4 departments, 6 staff, 5 reviews' },
  { id: 'crm',       icon: '📞', label: 'CRM / Sales', desc: 'companies, contacts, deals, activities — 4 companies, 4 contacts, 4 deals' },
  { id: 'custom',    icon: '✏️',  label: 'Custom SQL', desc: 'Paste your own DDL + INSERT statements' },
]

function SeederTab({ status, onStatusRefresh: _onStatusRefresh }: { status: LabStatus | null; onStatusRefresh: () => void }) {
  const [selected, setSelected] = useState('ecommerce')
  const [customSql, setCustomSql] = useState('-- CREATE TABLE ...\n-- INSERT INTO ...\n')
  const [loading, setLoading] = useState(false)
  const [log, setLog] = useState<string[]>([])
  const isRunning = status?.postgres_running ?? false
  const push = (line: string) => setLog((p) => [...p, line])

  async function seed() {
    setLoading(true)
    push(`⏳ Seeding dataset '${selected}'…`)
    try {
      const body: any = { dataset: selected }
      if (selected === 'custom') body.custom_ddl = customSql
      const r = await fetch(`${API_BASE}/api/lab/postgres/seed`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await r.json()
      push(d.success ? `✅ ${d.message}` : `❌ ${d.error}`)
    } catch (e: any) { push(`❌ Network error: ${e.message}`) }
    setLoading(false)
  }

  return (
    <div className="lab-tab-body">
      {!isRunning && (
        <div className="lab-warning-banner">
          ⚠ No Postgres container running. Go to the <strong>Services</strong> tab, pick Postgres and start one first.
        </div>
      )}
      <div className="lab-card">
        <h4 className="lab-card-title">🌱 Preset Datasets</h4>
        <p className="lab-hint">Pick a dataset to seed into the running Postgres. Tables are dropped and recreated on each seed.</p>
        <div className="lab-dataset-grid">
          {DATASETS.map((ds) => (
            <div key={ds.id}
              className={`lab-dataset-card ${selected === ds.id ? 'lab-dataset-card--selected' : ''}`}
              onClick={() => setSelected(ds.id)}>
              <div className="lab-dataset-icon">{ds.icon}</div>
              <div className="lab-dataset-label">{ds.label}</div>
              <div className="lab-dataset-desc">{ds.desc}</div>
            </div>
          ))}
        </div>
        {selected === 'custom' && (
          <div style={{ marginTop: 12 }}>
            <label className="lab-label">Custom DDL + INSERT SQL</label>
            <textarea className="lab-sql-editor" style={{ height: 180 }}
              value={customSql} onChange={(e) => setCustomSql(e.target.value)}
              spellCheck={false} placeholder="CREATE TABLE ...\nINSERT INTO ..." />
          </div>
        )}
        <button type="button" className="lab-btn lab-btn--primary" style={{ marginTop: 12 }}
          disabled={!isRunning || loading} onClick={seed}>
          {loading ? '⏳ Seeding…' : `🌱 Seed '${DATASETS.find(d => d.id === selected)?.label}' Dataset`}
        </button>
      </div>
      <div className="lab-card" style={{ marginTop: 16 }}>
        <h4 className="lab-card-title">📋 Activity Log</h4>
        <LogBox lines={log} />
      </div>
    </div>
  )
}

// ── PDF Studio Tab ────────────────────────────────────────────────────────────

const PDF_TEMPLATES = [
  { id: 'plain',   icon: '📄', label: 'Plain',   desc: 'Simple text document' },
  { id: 'report',  icon: '📊', label: 'Report',  desc: 'Styled report with header & date' },
  { id: 'bio',     icon: '👤', label: 'Bio',     desc: 'Profile / bio with section headings' },
  { id: 'invoice', icon: '🧾', label: 'Invoice', desc: 'Table-based invoice layout' },
]

const PDF_PRESETS: Record<string, { title: string; content: string }> = {
  plain: {
    title: 'Sample Test Document',
    content: 'This is a plain test document generated by the Research Lab.\n\nIt contains multiple paragraphs for testing the Docling parser and the agentic pipeline.\n\nFeel free to replace this content with any text you want to test with.',
  },
  report: {
    title: 'Q3 2024 Research Report',
    content: 'This report summarises the key findings from Q3 2024 research activities.\n\nKey findings indicate a 23% improvement in retrieval accuracy using hybrid search methods compared to dense-only baselines.\n\nRecommendations include adopting hybrid BM25 + semantic search for all production RAG pipelines and evaluating OpenSearch as the primary vector store backend.\n\nNext steps involve running A/B tests across three customer segments and publishing results in Q4.',
  },
  bio: {
    title: 'Wilson Shamim',
    content: '# Summary\nSenior AI/ML Engineer with 8 years of experience building production-grade agentic systems.\n\n## Skills\nPython, LangChain, FastAPI, React, PostgreSQL, Docker, Kubernetes, LLM fine-tuning\n\n## Experience\nIBM Research — Staff Engineer (2022–present)\nBuilt the Universal Agentic Framework for multi-tenant AI pipelines.\n\n## Education\nM.Sc. Computer Science — University of Toronto, 2016',
  },
  invoice: {
    title: 'Invoice #INV-2024-001',
    content: 'Item | Quantity | Unit Price | Total\nAgentic Framework License | 1 | $5,000 | $5,000\nProfessional Services | 10h | $200/h | $2,000\nSupport (Annual) | 1 | $1,500 | $1,500\n--- | --- | --- | ---\nTotal | | | $8,500',
  },
}

function PdfStudioTab({ status }: { status: LabStatus | null }) {
  const [template, setTemplate] = useState('report')
  const [title, setTitle] = useState(PDF_PRESETS.report.title)
  const [content, setContent] = useState(PDF_PRESETS.report.content)
  const [author, setAuthor] = useState('Research Lab')
  const [outputPath, setOutputPath] = useState('')
  const [loading, setLoading] = useState(false)
  const [log, setLog] = useState<string[]>([])
  const push = (line: string) => setLog((p) => [...p, line])

  function applyPreset(tmpl: string) {
    setTemplate(tmpl)
    const p = PDF_PRESETS[tmpl]
    if (p) { setTitle(p.title); setContent(p.content) }
  }

  async function generate() {
    setLoading(true)
    push(`⏳ Generating ${template} PDF…`)
    try {
      const r = await fetch(`${API_BASE}/api/lab/pdf/generate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content, author, template, output_path: outputPath }),
      })
      const d = await r.json()
      if (d.success) {
        push(`✅ PDF generated: ${d.path}`)
        push(`   Size: ${(d.size_bytes / 1024).toFixed(1)} KB`)
        push(`   💡 Use this path in a Docling node to parse and test with your agents.`)
      } else {
        push(`❌ ${d.error}`)
      }
    } catch (e: any) { push(`❌ Network error: ${e.message}`) }
    setLoading(false)
  }

  async function batchGenerate() {
    setLoading(true)
    push('⏳ Generating batch PDFs (one per template)…')
    try {
      const docs = Object.entries(PDF_PRESETS).map(([tmpl, preset]) => ({
        title: preset.title, content: preset.content, author, template: tmpl, output_path: '',
      }))
      const r = await fetch(`${API_BASE}/api/lab/pdf/batch`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ documents: docs, output_dir: outputPath || '' }),
      })
      const d = await r.json()
      push(`✅ Batch done: ${d.generated}/${d.total} generated.`)
      d.files?.forEach((f: any) => push(f.success ? `   • ${f.path} (${(f.size_bytes/1024).toFixed(1)} KB)` : `   ❌ ${f.title}: ${f.error}`))
    } catch (e: any) { push(`❌ Network error: ${e.message}`) }
    setLoading(false)
  }

  return (
    <div className="lab-tab-body">
      {!status?.reportlab_available && (
        <div className="lab-warning-banner">
          ⚠ <code>reportlab</code> not installed on the backend. Run: <code>pip install reportlab</code> then restart.
        </div>
      )}
      <div className="lab-two-col">
        <div className="lab-card">
          <h4 className="lab-card-title">📄 PDF Configuration</h4>

          <label className="lab-label">Template</label>
          <div className="lab-template-row">
            {PDF_TEMPLATES.map((t) => (
              <div key={t.id}
                className={`lab-template-card ${template === t.id ? 'lab-template-card--selected' : ''}`}
                onClick={() => applyPreset(t.id)}>
                <span className="lab-template-icon">{t.icon}</span>
                <span className="lab-template-label">{t.label}</span>
                <span className="lab-template-desc">{t.desc}</span>
              </div>
            ))}
          </div>

          <div className="lab-field" style={{ marginTop: 12 }}>
            <label className="lab-label">Title</label>
            <input type="text" className="lab-input" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="lab-field">
            <label className="lab-label">Author</label>
            <input type="text" className="lab-input" value={author} onChange={(e) => setAuthor(e.target.value)} />
          </div>
          <div className="lab-field">
            <label className="lab-label">Output Path <span style={{ fontWeight: 400, color: '#94a3b8' }}>(optional — leave blank for temp dir)</span></label>
            <input type="text" className="lab-input" placeholder="/path/to/output.pdf or a folder for batch"
              value={outputPath} onChange={(e) => setOutputPath(e.target.value)} />
          </div>
          <div className="lab-card-actions" style={{ gap: 8 }}>
            <button type="button" className="lab-btn lab-btn--primary" disabled={loading} onClick={generate}>
              {loading ? '⏳ Generating…' : '📄 Generate PDF'}
            </button>
            <button type="button" className="lab-btn lab-btn--secondary" disabled={loading} onClick={batchGenerate}>
              📦 Batch (all templates)
            </button>
          </div>
        </div>

        <div className="lab-card">
          <h4 className="lab-card-title">✏️ Content Editor</h4>
          <textarea className="lab-sql-editor" style={{ height: 280 }}
            value={content} onChange={(e) => setContent(e.target.value)} spellCheck={false}
            placeholder="Write the document content here…" />
          <div className="lab-hint" style={{ marginTop: 6 }}>
            For <strong>bio</strong> template: use <code># Heading</code> and <code>## Sub-heading</code> markdown.<br />
            For <strong>invoice</strong> template: use <code>Col1 | Col2 | Col3</code> pipe-separated rows.
          </div>
        </div>
      </div>

      <div className="lab-card" style={{ marginTop: 16 }}>
        <h4 className="lab-card-title">📋 Activity Log</h4>
        <LogBox lines={log} />
      </div>
    </div>
  )
}

// ── Ollama Tab ────────────────────────────────────────────────────────────────

interface OllamaModel {
  name: string
  size: number
  modified_at: string
  family: string
  parameter_size: string
  quantization_level: string
}

interface PullEvent {
  status: string
  digest: string
  total: number
  completed: number
  percent: number
  done: boolean
  error?: string
}

function formatBytes(bytes: number): string {
  if (!bytes) return '—'
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`
  return `${(bytes / 1e3).toFixed(1)} KB`
}

function OllamaTab() {
  const [models, setModels] = useState<OllamaModel[]>([])
  const [available, setAvailable] = useState<boolean | null>(null)
  const [modelName, setModelName] = useState('')
  const [pulling, setPulling] = useState(false)
  const [pullLog, setPullLog] = useState<PullEvent[]>([])
  const [pullDone, setPullDone] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  async function fetchModels() {
    try {
      const r = await fetch(`${API_BASE}/api/lab/ollama/list`)
      const d = await r.json()
      setAvailable(d.ollama_available)
      setModels(d.models || [])
    } catch {
      setAvailable(false)
    }
  }

  useEffect(() => { fetchModels() }, [])
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [pullLog])

  async function pullModel() {
    const name = modelName.trim()
    if (!name) return
    setPulling(true)
    setPullLog([])
    setPullDone(false)

    try {
      const resp = await fetch(`${API_BASE}/api/lab/ollama/pull`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: name }),
      })
      const reader = resp.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const evt: PullEvent = JSON.parse(line.slice(6))
            setPullLog(prev => {
              // update last line if same digest/status, else append
              const last = prev[prev.length - 1]
              if (last && last.digest && last.digest === evt.digest) {
                return [...prev.slice(0, -1), evt]
              }
              return [...prev, evt]
            })
            if (evt.done || evt.error) {
              setPullDone(true)
              fetchModels()
            }
          } catch { /* skip malformed */ }
        }
      }
    } catch (e: any) {
      setPullLog(prev => [...prev, { status: `Error: ${e.message}`, digest: '', total: 0, completed: 0, percent: 0, done: true, error: e.message }])
      setPullDone(true)
    }

    setPulling(false)
  }

  async function deleteModel(name: string) {
    try {
      await fetch(`${API_BASE}/api/lab/ollama/${encodeURIComponent(name)}`, { method: 'DELETE' })
      setDeleteConfirm(null)
      fetchModels()
    } catch { /* ignore */ }
  }

  const lastEvent = pullLog[pullLog.length - 1]

  return (
    <div className="lab-section">
      {/* Status */}
      {available === false && (
        <div className="lab-alert lab-alert--warn">
          ⚠️ Ollama is not reachable at <code>http://localhost:11434</code>. Make sure Ollama is running (<code>ollama serve</code>).
        </div>
      )}

      {/* Pull a model */}
      <div className="lab-card">
        <h3 className="lab-card-title">📥 Pull a Model</h3>
        <p className="lab-hint">
          Enter any model name from <a href="https://ollama.com/library" target="_blank" rel="noreferrer">ollama.com/library</a>, e.g.{' '}
          <code>llama3.2</code>, <code>ibm/granite4</code>, <code>mistral</code>, <code>nomic-embed-text</code>.
        </p>
        <div className="lab-row">
          <input
            className="lab-input"
            placeholder="e.g. llama3.2 or ibm/granite4"
            value={modelName}
            onChange={e => setModelName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !pulling && pullModel()}
            disabled={pulling}
          />
          <button
            className="lab-btn lab-btn--primary"
            onClick={pullModel}
            disabled={pulling || !modelName.trim()}
          >
            {pulling ? '⏳ Pulling…' : '⬇️ Pull'}
          </button>
        </div>

        {/* Progress */}
        {pullLog.length > 0 && (
          <div className="lab-pull-log">
            {lastEvent && !lastEvent.error && !lastEvent.done && lastEvent.total > 0 && (
              <div className="lab-pull-bar-wrap">
                <div className="lab-pull-bar" style={{ width: `${lastEvent.percent}%` }} />
              </div>
            )}
            <div className="lab-log-box">
              {pullLog.map((evt, i) => (
                <div key={i} className={evt.error ? 'lab-log-line lab-log-line--error' : 'lab-log-line'}>
                  {evt.error
                    ? `❌ ${evt.error}`
                    : evt.done
                      ? `✅ ${evt.status}`
                      : evt.total > 0
                        ? `${evt.status} ${evt.digest.slice(0, 14)}… ${evt.percent}% (${formatBytes(evt.completed)} / ${formatBytes(evt.total)})`
                        : `${evt.status}`
                  }
                </div>
              ))}
              <div ref={logEndRef} />
            </div>
            {pullDone && (
              <button className="lab-btn lab-btn--ghost" onClick={() => { setPullLog([]); setPullDone(false); setModelName('') }}>
                Clear
              </button>
            )}
          </div>
        )}
      </div>

      {/* Installed models */}
      <div className="lab-card">
        <div className="lab-card-header">
          <h3 className="lab-card-title">🗂️ Installed Models ({models.length})</h3>
          <button className="lab-btn lab-btn--ghost" onClick={fetchModels}>↻ Refresh</button>
        </div>
        {models.length === 0 ? (
          <p className="lab-hint">No models installed yet. Pull one above.</p>
        ) : (
          <table className="lab-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Family</th>
                <th>Params</th>
                <th>Quant</th>
                <th>Size</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {models.map(m => (
                <tr key={m.name}>
                  <td><code>{m.name}</code></td>
                  <td>{m.family || '—'}</td>
                  <td>{m.parameter_size || '—'}</td>
                  <td>{m.quantization_level || '—'}</td>
                  <td>{formatBytes(m.size)}</td>
                  <td>
                    {deleteConfirm === m.name ? (
                      <span className="lab-delete-confirm">
                        Delete?{' '}
                        <button className="lab-btn lab-btn--danger lab-btn--xs" onClick={() => deleteModel(m.name)}>Yes</button>{' '}
                        <button className="lab-btn lab-btn--ghost lab-btn--xs" onClick={() => setDeleteConfirm(null)}>No</button>
                      </span>
                    ) : (
                      <button className="lab-btn lab-btn--ghost lab-btn--xs" onClick={() => setDeleteConfirm(m.name)}>🗑️</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── llama.cpp Tab ─────────────────────────────────────────────────────────────

interface LlamaCppStatus {
  available: boolean
  base_url: string
  status?: 'ok' | 'loading'
  models?: string[]
  model_path?: string
  n_ctx?: number
  total_slots?: number
  build_info?: string
  error?: string
}

type LlamaRole = 'chat' | 'embeddings'

const LLAMACPP_PRESETS: { repo: string; label: string; role: LlamaRole }[] = [
  { repo: 'ggml-org/gemma-3-1b-it-GGUF',           label: 'Gemma 3 1B — tiny, fast chat',      role: 'chat' },
  { repo: 'ggml-org/gemma-3-4b-it-GGUF',           label: 'Gemma 3 4B — balanced chat',        role: 'chat' },
  { repo: 'ggml-org/Qwen2.5-Coder-7B-Q8_0-GGUF',   label: 'Qwen2.5 Coder 7B — code',           role: 'chat' },
  { repo: 'ggml-org/embeddinggemma-300M-GGUF',     label: 'EmbeddingGemma 300M — embeddings',  role: 'embeddings' },
  { repo: 'nomic-ai/nomic-embed-text-v1.5-GGUF',   label: 'nomic-embed-text v1.5 — embeddings', role: 'embeddings' },
]

const LLAMACPP_INSTALL: { os: string; cmd: string }[] = [
  { os: 'macOS / Linux (Homebrew)', cmd: 'brew install llama.cpp' },
  { os: 'Windows (winget)',         cmd: 'winget install llama.cpp' },
  { os: 'Docker (no install)',      cmd: 'docker pull ghcr.io/ggml-org/llama.cpp:server' },
]

interface InstallResult { success: boolean; error?: string }

/** POST to a Lab install endpoint and feed its SSE stream ({line} … {done, success, error}). */
async function streamInstall(path: string, body: object, onLine: (line: string) => void, onDone: (r: InstallResult) => void) {
  try {
    const resp = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!resp.ok) throw new Error(`Backend returned HTTP ${resp.status}`)
    const reader = resp.body!.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const evt = JSON.parse(line.slice(6))
          if (evt.line) onLine(evt.line)
          if (evt.done) onDone({ success: evt.success, error: evt.error })
        } catch { /* skip malformed */ }
      }
    }
  } catch (e: any) {
    onDone({ success: false, error: e.message })
  }
}

function InstallLog({ lines, result }: { lines: string[]; result: InstallResult | null }) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [lines])
  if (lines.length === 0 && !result) return null
  return (
    <div className="lab-pull-log">
      <div className="lab-log-box">
        {lines.map((l, i) => <div key={i} className="lab-log-line">{l}</div>)}
        {result && (
          <div className={result.success ? 'lab-log-line' : 'lab-log-line lab-log-line--error'}>
            {result.success ? '✅ Done' : `❌ ${result.error}`}
          </div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  )
}

function CopyCmd({ cmd }: { cmd: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(cmd)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard blocked */ }
  }
  return (
    <div className="lab-cmd">
      <code className="lab-cmd-text">{cmd}</code>
      <button type="button" className="lab-btn lab-btn--ghost lab-btn--xs" onClick={copy}>{copied ? '✓ Copied' : '📋 Copy'}</button>
    </div>
  )
}

interface LlamaCppServer {
  port: number
  runtime: 'native' | 'docker' | 'podman'
  name: string
  repo: string
  mode: LlamaRole
  running: boolean
  exit_code?: number | null
}

interface LlamaCppSetup {
  platform: string
  binary: string | null
  version: string
  installers: { brew: boolean; winget: boolean }
  runtimes: Record<'docker' | 'podman', string | null>
  image: string
  servers: LlamaCppServer[]
}

type LlamaRuntime = 'native' | 'docker' | 'podman'

function LlamaCppTab() {
  const [baseUrl, setBaseUrl] = useState('http://localhost:8080')
  const [status, setStatus] = useState<LlamaCppStatus | null>(null)
  const [checking, setChecking] = useState(false)
  const [setup, setSetup] = useState<LlamaCppSetup | null>(null)
  const [setupError, setSetupError] = useState('')
  const [installing, setInstalling] = useState<string | null>(null)
  const [installLog, setInstallLog] = useState<string[]>([])
  const [installResult, setInstallResult] = useState<InstallResult | null>(null)
  const [repo, setRepo] = useState(LLAMACPP_PRESETS[0].repo)
  const [role, setRole] = useState<LlamaRole>('chat')
  const [port, setPort] = useState(8080)
  const [ctx, setCtx] = useState(8192)
  const [runtime, setRuntime] = useState<LlamaRuntime>('native')
  const [starting, setStarting] = useState(false)
  const [startMsg, setStartMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [logsPort, setLogsPort] = useState<number | null>(null)
  const [logs, setLogs] = useState('')

  async function checkStatus(url = baseUrl) {
    setChecking(true)
    try {
      const r = await fetch(`${API_BASE}/api/lab/llamacpp/status?base_url=${encodeURIComponent(url)}`)
      if (!r.ok) throw new Error(`backend returned HTTP ${r.status} — restart the backend to load the llama.cpp Lab endpoints`)
      setStatus(await r.json())
    } catch (e: any) {
      setStatus({ available: false, base_url: url, error: e.message })
    }
    setChecking(false)
  }

  async function fetchSetup() {
    try {
      const r = await fetch(`${API_BASE}/api/lab/llamacpp/setup`)
      if (!r.ok) throw new Error(`Backend returned HTTP ${r.status} — restart the backend to load the llama.cpp Lab endpoints.`)
      const d: LlamaCppSetup = await r.json()
      setSetup(d)
      setSetupError('')
      setRuntime(prev => {
        if (prev === 'native' && d.binary) return prev
        if (prev !== 'native' && !d.runtimes[prev]) return prev
        if (d.binary) return 'native'
        if (!d.runtimes.podman) return 'podman'
        if (!d.runtimes.docker) return 'docker'
        return prev
      })
    } catch (e: any) {
      setSetupError(e.message)
    }
  }

  useEffect(() => { checkStatus(); fetchSetup() }, [])

  // Poll logs + status while a server's log panel is open
  useEffect(() => {
    if (logsPort === null) return
    let stop = false
    const url = `http://localhost:${logsPort}`
    async function tick() {
      try {
        const r = await fetch(`${API_BASE}/api/lab/llamacpp/logs?port=${logsPort}`)
        const d = await r.json()
        if (!stop) setLogs(d.logs ?? d.error ?? '')
      } catch { /* backend busy */ }
      if (!stop && baseUrl === url) checkStatus(url)
    }
    tick()
    const id = setInterval(tick, 3000)
    return () => { stop = true; clearInterval(id) }
  }, [logsPort, baseUrl])

  function pickPreset(r: string) {
    setRepo(r)
    const preset = LLAMACPP_PRESETS.find(p => p.repo === r)
    if (preset) {
      setRole(preset.role)
      setPort(preset.role === 'embeddings' ? 8081 : 8080)
    }
  }

  async function install(method: string) {
    setInstalling(method)
    setInstallLog([])
    setInstallResult(null)
    await streamInstall('/api/lab/llamacpp/install', { method },
      line => setInstallLog(prev => [...prev.slice(-300), line]), setInstallResult)
    setInstalling(null)
    fetchSetup()
  }

  async function startServer() {
    setStarting(true)
    setStartMsg(null)
    try {
      const r = await fetch(`${API_BASE}/api/lab/llamacpp/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo: repo.trim(), mode: role, port, ctx, runtime }),
      })
      const d = await r.json()
      if (d.success) {
        setStartMsg({ ok: true, text: d.message })
        const url = `http://localhost:${port}`
        setBaseUrl(url)
        setLogsPort(port)
      } else {
        setStartMsg({ ok: false, text: d.error || d.detail || `HTTP ${r.status}` })
      }
    } catch (e: any) {
      setStartMsg({ ok: false, text: e.message })
    }
    setStarting(false)
    fetchSetup()
  }

  async function stopServer(p: number) {
    try {
      await fetch(`${API_BASE}/api/lab/llamacpp/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port: p }),
      })
    } catch { /* ignore */ }
    if (logsPort === p) setLogsPort(null)
    fetchSetup()
    checkStatus()
  }

  function selectServer(p: number) {
    const url = `http://localhost:${p}`
    setBaseUrl(url)
    checkStatus(url)
  }

  const flags = [
    `-hf ${repo.trim() || '<hf-repo>'}`,
    `--port ${port}`,
    role === 'chat' ? `-c ${ctx}` : '--embeddings',
  ]
  const manualCmd = runtime === 'native'
    ? `llama-server ${flags.join(' ')}`
    : `${runtime} run --rm -p ${port}:${port} -v ~/.cache/llama.cpp:/root/.cache/llama.cpp ghcr.io/ggml-org/llama.cpp:server ${flags.join(' ')} --host 0.0.0.0`

  const runtimeProblem = (rt: LlamaRuntime): string | null => {
    if (!setup) return 'Checking…'
    if (rt === 'native') return setup.binary ? null : 'llama-server is not installed'
    return setup.runtimes[rt]
  }
  const installers: { id: string; label: string; problem: string | null }[] = setup ? [
    ...(setup.installers.brew ? [{ id: 'brew', label: '🍺 Install with Homebrew', problem: null }] : []),
    ...(setup.installers.winget ? [{ id: 'winget', label: '🪟 Install with winget', problem: null }] : []),
    { id: 'podman', label: '🦭 Pull image with Podman', problem: setup.runtimes.podman },
    { id: 'docker', label: '🐳 Pull image with Docker', problem: setup.runtimes.docker },
  ] : []
  const servers = setup?.servers ?? []

  return (
    <div className="lab-section">
      {setupError && <div className="lab-alert lab-alert--warn">⚠️ {setupError}</div>}

      {/* Server status */}
      <div className="lab-card">
        <div className="lab-card-header">
          <h3 className="lab-card-title">📡 Server Status</h3>
        </div>
        <div className="lab-row">
          <input
            className="lab-input"
            placeholder="http://localhost:8080"
            value={baseUrl}
            onChange={e => setBaseUrl(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !checking && checkStatus()}
          />
          <button className="lab-btn lab-btn--primary" onClick={() => checkStatus()} disabled={checking || !baseUrl.trim()}>
            {checking ? '⏳ Checking…' : '↻ Check'}
          </button>
        </div>

        {status && !status.available && (
          <div className="lab-alert lab-alert--warn" style={{ marginTop: 12, marginBottom: 0 }}>
            ⚠️ llama-server is not reachable at <code>{status.base_url || baseUrl}</code>{status.error ? ` — ${status.error}` : ''}.
          </div>
        )}
        {status?.available && status.status === 'loading' && (
          <div className="lab-alert lab-alert--warn" style={{ marginTop: 12, marginBottom: 0 }}>
            ⏳ llama-server is up and still loading the model.
          </div>
        )}
        {status?.available && status.status === 'ok' && (
          <table className="lab-table" style={{ marginTop: 12 }}>
            <tbody>
              <tr><th>Status</th><td>✅ Running</td></tr>
              <tr><th>Model id</th><td><code>{status.models?.join(', ') || '—'}</code></td></tr>
              <tr><th>Model file</th><td><code>{status.model_path || '—'}</code></td></tr>
              <tr><th>Context</th><td>{status.n_ctx ? `${status.n_ctx.toLocaleString()} tokens` : '—'}{status.total_slots ? ` · ${status.total_slots} slot(s)` : ''}</td></tr>
              {status.build_info && <tr><th>Build</th><td>{status.build_info}</td></tr>}
            </tbody>
          </table>
        )}
        <p className="lab-hint" style={{ marginTop: 12, marginBottom: 0 }}>
          To use it in a pipeline, pick <b>llama.cpp (Local)</b> on an LLM or Embedding node and set its Base URL to this address.
        </p>
      </div>

      {/* Install */}
      <div className="lab-card">
        <div className="lab-card-header">
          <h3 className="lab-card-title">1️⃣ Install llama.cpp</h3>
          <button className="lab-btn lab-btn--ghost" onClick={fetchSetup}>↻ Refresh</button>
        </div>
        {setup?.binary ? (
          <p className="lab-hint">✅ <b>llama-server</b> is installed at <code>{setup.binary}</code>{setup.version ? ` (${setup.version})` : ''}.</p>
        ) : (
          <p className="lab-hint">
            Install llama-server on this machine, or pull the official server image to run it in a container instead.
          </p>
        )}
        <div className="lab-row" style={{ flexWrap: 'wrap' }}>
          {installers.map(i => (
            <button key={i.id} className="lab-btn lab-btn--primary" disabled={!!installing || !!i.problem}
              title={i.problem ?? ''} onClick={() => install(i.id)}>
              {installing === i.id ? '⏳ Installing…' : i.label}
            </button>
          ))}
        </div>
        <InstallLog lines={installLog} result={installResult} />
        <details className="lab-details">
          <summary>Install manually</summary>
          <p className="lab-hint">
            Other options (prebuilt binaries, building with CUDA / Metal / Vulkan) are on{' '}
            <a href="https://github.com/ggml-org/llama.cpp" target="_blank" rel="noreferrer">github.com/ggml-org/llama.cpp</a>.
          </p>
          {LLAMACPP_INSTALL.map(i => (
            <div key={i.os} className="lab-cmd-row">
              <span className="lab-cmd-label">{i.os}</span>
              <CopyCmd cmd={i.cmd} />
            </div>
          ))}
        </details>
      </div>

      {/* Start a server */}
      <div className="lab-card">
        <h3 className="lab-card-title">2️⃣ Start a Model</h3>
        <p className="lab-hint">
          llama-server serves one model per process and downloads it from Hugging Face on first start, which can take a few minutes.
          Start a second server on another port for embeddings.
        </p>
        <div className="lab-form-grid">
          <label className="lab-field">
            <span>Preset</span>
            <select className="lab-input" value={LLAMACPP_PRESETS.some(p => p.repo === repo) ? repo : ''} onChange={e => e.target.value && pickPreset(e.target.value)}>
              <option value="">Custom…</option>
              {LLAMACPP_PRESETS.map(p => <option key={p.repo} value={p.repo}>{p.label}</option>)}
            </select>
          </label>
          <label className="lab-field">
            <span>Hugging Face repo (GGUF)</span>
            <input className="lab-input" value={repo} onChange={e => setRepo(e.target.value)} placeholder="user/model-GGUF[:quant]" />
          </label>
          <label className="lab-field">
            <span>Mode</span>
            <select className="lab-input" value={role} onChange={e => setRole(e.target.value as LlamaRole)}>
              <option value="chat">Chat / completion</option>
              <option value="embeddings">Embeddings</option>
            </select>
          </label>
          <label className="lab-field">
            <span>Port</span>
            <input className="lab-input" type="number" min={1024} max={65535} value={port} onChange={e => setPort(Number(e.target.value) || 8080)} />
          </label>
          {role === 'chat' && (
            <label className="lab-field">
              <span>Context size</span>
              <input className="lab-input" type="number" min={512} step={512} value={ctx} onChange={e => setCtx(Number(e.target.value) || 4096)} />
            </label>
          )}
          <label className="lab-field">
            <span>Run with</span>
            <select className="lab-input" value={runtime} onChange={e => setRuntime(e.target.value as LlamaRuntime)}>
              {(['native', 'podman', 'docker'] as LlamaRuntime[]).map(rt => (
                <option key={rt} value={rt} disabled={!!runtimeProblem(rt)}>
                  {rt === 'native' ? 'This machine (llama-server)' : rt === 'podman' ? 'Podman container' : 'Docker container'}
                  {runtimeProblem(rt) ? ' — unavailable' : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="lab-row">
          <button className="lab-btn lab-btn--primary" onClick={startServer}
            disabled={starting || !repo.trim() || !!runtimeProblem(runtime)} title={runtimeProblem(runtime) ?? ''}>
            {starting ? '⏳ Starting…' : '▶ Start server'}
          </button>
          {runtimeProblem(runtime) && setup && <span className="lab-hint" style={{ margin: 0 }}>{runtimeProblem(runtime)}</span>}
        </div>
        {startMsg && (
          <div className={`lab-alert ${startMsg.ok ? 'lab-alert--ok' : 'lab-alert--warn'}`} style={{ marginTop: 12, marginBottom: 0 }}>
            {startMsg.ok ? '🚀' : '⚠️'} {startMsg.text}
          </div>
        )}
        <details className="lab-details">
          <summary>Run it yourself instead</summary>
          <CopyCmd cmd={manualCmd} />
        </details>
      </div>

      {/* Managed servers */}
      <div className="lab-card">
        <div className="lab-card-header">
          <h3 className="lab-card-title">🗂️ Lab Servers ({servers.length})</h3>
          <button className="lab-btn lab-btn--ghost" onClick={fetchSetup}>↻ Refresh</button>
        </div>
        {servers.length === 0 ? (
          <p className="lab-hint">No servers started from the Lab yet.</p>
        ) : (
          <table className="lab-table">
            <thead>
              <tr><th>Port</th><th>Model</th><th>Mode</th><th>Runs on</th><th>State</th><th></th></tr>
            </thead>
            <tbody>
              {servers.map(sv => (
                <tr key={`${sv.runtime}-${sv.port}`}>
                  <td><code>{sv.port}</code></td>
                  <td><code>{sv.repo || '—'}</code></td>
                  <td>{sv.mode}</td>
                  <td>{sv.runtime}</td>
                  <td>{sv.running ? '🟢 running' : `⚪ stopped${sv.exit_code != null ? ` (exit ${sv.exit_code})` : ''}`}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {sv.running && <button className="lab-btn lab-btn--ghost lab-btn--xs" onClick={() => selectServer(sv.port)}>Check</button>}{' '}
                    <button className="lab-btn lab-btn--ghost lab-btn--xs" onClick={() => setLogsPort(logsPort === sv.port ? null : sv.port)}>
                      {logsPort === sv.port ? 'Hide logs' : 'Logs'}
                    </button>{' '}
                    <button className="lab-btn lab-btn--danger lab-btn--xs" onClick={() => stopServer(sv.port)}>
                      {sv.running ? 'Stop' : 'Remove'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {logsPort !== null && (
          <div className="lab-pull-log">
            <div className="lab-hint" style={{ marginBottom: 4 }}>Logs — port {logsPort} (refreshing every 3s)</div>
            <pre className="lab-log-box lab-log-pre">{logs || 'Waiting for output…'}</pre>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main LabView ──────────────────────────────────────────────────────────────

export function LabView() {
  const [activeTab, setActiveTab] = useState<LabTab>('services')
  const [status, setStatus] = useState<LabStatus | null>(null)

  async function fetchStatus() {
    try {
      const r = await fetch(`${API_BASE}/api/lab/status`)
      const d = await r.json()
      setStatus(d)
    } catch { /* backend may not be running */ }
  }

  useEffect(() => { fetchStatus() }, [])

  const TABS: { id: LabTab; icon: string; label: string }[] = [
    { id: 'services', icon: '🧱', label: 'Services' },
    { id: 'seeder',   icon: '🌱', label: 'Data Seeder' },
    { id: 'pdf',      icon: '📄', label: 'PDF Studio' },
    { id: 'ollama',   icon: '🦙', label: 'Ollama Models' },
    { id: 'llamacpp', icon: '🦙', label: 'llama.cpp' },
  ]

  return (
    <div className="lab-view">
      {/* Header */}
      <div className="lab-header">
        <div className="lab-header-left">
          <h2 className="lab-title">🧪 Research Lab</h2>
          <p className="lab-subtitle">Spin up local test infrastructure and generate test data for your agentic pipelines.</p>
        </div>
        <div className="lab-env-badges">
          {status ? (
            <>
              <Badge ok={status.docker_available} label="Docker" />
              <Badge ok={status.podman_available} label="Podman" />
              <Badge ok={!!status.kubernetes_available} label="Kubernetes" />
              <Badge ok={status.reportlab_available} label="ReportLab" />
              <Badge ok={status.postgres_running} label="Postgres" />
            </>
          ) : (
            <span className="lab-badge lab-badge--off">⏳ Checking environment…</span>
          )}
          <button type="button" className="lab-refresh-btn" onClick={fetchStatus}>↻</button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="lab-tab-bar">
        {TABS.map((t) => (
          <button key={t.id} type="button"
            className={`lab-tab-btn ${activeTab === t.id ? 'lab-tab-btn--active' : ''}`}
            onClick={() => setActiveTab(t.id)}>
            <span>{t.icon}</span> {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="lab-content">
        {activeTab === 'services' && <ServicesTab status={status} onStatusRefresh={fetchStatus} />}
        {activeTab === 'seeder'   && <SeederTab   status={status} onStatusRefresh={fetchStatus} />}
        {activeTab === 'pdf'      && <PdfStudioTab status={status} />}
        {activeTab === 'ollama'   && <OllamaTab />}
        {activeTab === 'llamacpp' && <LlamaCppTab />}
      </div>
    </div>
  )
}
