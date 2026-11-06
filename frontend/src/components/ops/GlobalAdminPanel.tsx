import { useState, useCallback, useEffect } from 'react'
import { API_BASE } from '../../types'

interface PipelineStat {
  id: string
  name: string
  status: string
  version: number
  run_count: number
  cost_usd: number
  tokens: number
  last_run: string | null
}

interface Stats {
  totals: {
    pipelines: number
    published: number
    drafts: number
    traces: number
    errors: number
    cost_usd: number
    tokens: number
    eval_runs: number
  }
  pipelines: PipelineStat[]
}

interface Props {
  /** Called when a pipeline is deleted so the parent can refresh app list */
  onPipelineDeleted: (id: string) => void
  onPipelinesCleared: () => void
  /** Navigate to Build view for this pipeline */
  onOpenPipeline: (id: string) => void
  /** 'system' = health, integrations and per-pipeline stats; 'danger' = bulk, irreversible clean-up. */
  section: 'system' | 'danger'
}

export function GlobalAdminPanel({ onPipelineDeleted, onPipelinesCleared, onOpenPipeline, section }: Props) {
  const [stats, setStats]     = useState<Stats | null>(null)
  const [loading, setLoading] = useState(false)
  const [health, setHealth]   = useState<'unknown' | 'ok' | 'error'>('unknown')
  const [langfuse, setLangfuse] = useState<{ enabled: boolean; redact: boolean } | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const fetchStats = useCallback(() => {
    setLoading(true)
    fetch(`${API_BASE}/api/apps/stats/summary`)
      .then((r) => r.json())
      .then(setStats)
      .catch(() => setStats(null))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    fetchStats()
    fetch(`${API_BASE}/health`)
      .then((r) => r.ok ? setHealth('ok') : setHealth('error'))
      .catch(() => setHealth('error'))
    fetch(`${API_BASE}/api/tools/runtime-status`)
      .then((r) => r.json())
      .then((s) => setLangfuse(s?.langfuse ?? null))
      .catch(() => setLangfuse(null))
  }, [fetchStats])

  const toggleSelect = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const selectAll = () => {
    if (!stats) return
    setSelected(new Set(stats.pipelines.map((p) => p.id)))
  }

  const clearSelection = () => setSelected(new Set())

  const deleteSelected = async () => {
    if (selected.size === 0) return
    if (!window.confirm(`Delete ${selected.size} pipeline(s)? This cannot be undone.`)) return
    await Promise.all(
      Array.from(selected).map((id) =>
        fetch(`${API_BASE}/api/apps/${id}`, { method: 'DELETE' })
      )
    )
    selected.forEach((id) => onPipelineDeleted(id))
    setSelected(new Set())
    fetchStats()
  }

  const deleteAll = async () => {
    if (!window.confirm('Delete ALL pipelines? This is irreversible.')) return
    await fetch(`${API_BASE}/api/apps`, { method: 'DELETE' })
    onPipelinesCleared()
    setSelected(new Set())
    fetchStats()
  }

  const clearAllTraces = async () => {
    if (!window.confirm('Clear all trace records across all pipelines?')) return
    await fetch(`${API_BASE}/api/traces`, { method: 'DELETE' })
    fetchStats()
  }

  const t = stats?.totals

  if (section === 'danger') {
    return (
      <div className="settings-danger-list">
        <div className="settings-danger-item">
          <div>
            <strong>Clear all traces</strong>
            <p>Removes every trace record across all pipelines{t ? ` (${t.traces.toLocaleString()} now)` : ''}. Runs, costs and history views will be empty.</p>
          </div>
          <button type="button" className="ops-danger-btn" onClick={clearAllTraces}>Clear traces</button>
        </div>
        <div className="settings-danger-item">
          <div>
            <strong>Delete all pipelines</strong>
            <p>Permanently deletes every pipeline in this project{t ? ` (${t.pipelines} now)` : ''}, drafts and published versions included.</p>
          </div>
          <button type="button" className="ops-danger-btn" onClick={deleteAll}>Delete all pipelines</button>
        </div>
      </div>
    )
  }

  return (
    <div className="ops-panel ops-admin-panel">
      {/* Toolbar */}
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">Status</span>
          <span className={`ops-health-badge ops-health-badge--${health}`}>
            {health === 'ok' ? '● Connected' : health === 'error' ? '● Unreachable' : '● Checking…'}
          </span>
          {langfuse && (
            <span
              className="ops-count-badge"
              title="Configured via LANGFUSE_* env vars on the backend"
            >
              Langfuse: {langfuse.enabled ? (langfuse.redact ? 'on (redacted)' : 'on') : 'off'}
            </span>
          )}
        </div>
        <div className="ops-toolbar-right">
          <button type="button" className="ops-refresh-btn" onClick={fetchStats} disabled={loading}>
            {loading ? 'Loading…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {/* Summary cards */}
      {t && (
        <div className="ops-summary-cards">
          <div className="ops-summary-card">
            <span className="ops-summary-card-value">{t.pipelines}</span>
            <span className="ops-summary-card-label">Pipelines</span>
          </div>
          <div className="ops-summary-card ops-summary-card--green">
            <span className="ops-summary-card-value">{t.published}</span>
            <span className="ops-summary-card-label">Published</span>
          </div>
          <div className="ops-summary-card ops-summary-card--yellow">
            <span className="ops-summary-card-value">{t.drafts}</span>
            <span className="ops-summary-card-label">Drafts</span>
          </div>
          <div className="ops-summary-card">
            <span className="ops-summary-card-value">{t.traces.toLocaleString()}</span>
            <span className="ops-summary-card-label">Total Traces</span>
          </div>
          <div className="ops-summary-card ops-summary-card--red">
            <span className="ops-summary-card-value">{t.errors}</span>
            <span className="ops-summary-card-label">Errors</span>
          </div>
          <div className="ops-summary-card">
            <span className="ops-summary-card-value">${t.cost_usd.toFixed(4)}</span>
            <span className="ops-summary-card-label">Total Cost</span>
          </div>
          <div className="ops-summary-card">
            <span className="ops-summary-card-value">{t.tokens.toLocaleString()}</span>
            <span className="ops-summary-card-label">Total Tokens</span>
          </div>
          <div className="ops-summary-card">
            <span className="ops-summary-card-value">{t.eval_runs}</span>
            <span className="ops-summary-card-label">Eval Runs</span>
          </div>
        </div>
      )}

      {/* Pipeline table */}
      <div className="ops-admin-section-title">
        <span>Pipelines</span>
        {stats && stats.pipelines.length > 0 && (
          <div className="ops-admin-bulk-actions">
            {selected.size > 0 ? (
              <>
                <span className="ops-selected-count">{selected.size} selected</span>
                <button type="button" className="ops-link-btn" onClick={clearSelection}>Clear</button>
                <button type="button" className="ops-danger-btn ops-danger-btn--sm" onClick={deleteSelected}>
                  Delete Selected
                </button>
              </>
            ) : (
              <button type="button" className="ops-link-btn" onClick={selectAll}>Select All</button>
            )}
          </div>
        )}
      </div>

      {stats && stats.pipelines.length > 0 && (
        <div className="ops-table-header ops-pipeline-header">
          <span style={{ width: 24 }} />
          <span className="ops-pipe-col-name">Pipeline</span>
          <span className="ops-pipe-col-status">Status</span>
          <span className="ops-pipe-col-runs">Runs</span>
          <span className="ops-pipe-col-tokens">Tokens</span>
          <span className="ops-pipe-col-cost">Cost</span>
          <span className="ops-pipe-col-last">Last Run</span>
          <span className="ops-pipe-col-actions" />
        </div>
      )}

      <div className="ops-list">
        {!stats && !loading && (
          <div className="ops-empty">Backend unreachable — cannot load pipeline stats.</div>
        )}
        {stats?.pipelines.length === 0 && (
          <div className="ops-empty">No pipelines yet.</div>
        )}
        {stats?.pipelines.map((p) => (
          <div
            key={p.id}
            className={`ops-pipeline-row${selected.has(p.id) ? ' ops-pipeline-row--selected' : ''}`}
          >
            <input
              type="checkbox"
              className="ops-checkbox"
              checked={selected.has(p.id)}
              onChange={() => toggleSelect(p.id)}
            />
            <span className="ops-pipe-col-name">
              <button
                type="button"
                className="ops-pipe-name-btn"
                onClick={() => onOpenPipeline(p.id)}
                title="Open in Build view"
              >
                {p.name}
              </button>
            </span>
            <span className="ops-pipe-col-status">
              <span className={`ops-status-pill ops-status-pill--${p.status}`}>
                {p.status === 'published' ? `v${p.version} Published` : 'Draft'}
              </span>
            </span>
            <span className="ops-pipe-col-runs">{p.run_count}</span>
            <span className="ops-pipe-col-tokens">{p.tokens.toLocaleString()}</span>
            <span className="ops-pipe-col-cost">${p.cost_usd.toFixed(5)}</span>
            <span className="ops-pipe-col-last">
              {p.last_run ? new Date(p.last_run).toLocaleString() : '—'}
            </span>
            <div className="ops-pipe-col-actions">
              <button
                type="button"
                className="ops-open-btn"
                onClick={() => onOpenPipeline(p.id)}
              >
                Open
              </button>
              <button
                type="button"
                className="ops-row-delete-btn"
                onClick={async () => {
                  if (!window.confirm(`Delete pipeline "${p.name}"?`)) return
                  await fetch(`${API_BASE}/api/apps/${p.id}`, { method: 'DELETE' })
                  onPipelineDeleted(p.id)
                  fetchStats()
                }}
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
