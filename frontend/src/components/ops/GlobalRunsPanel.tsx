import { useState, useCallback, useEffect } from 'react'
import { API_BASE, type TraceRecord } from '../../types'

interface AppRecord {
  id: string
  name: string
}

interface Props {
  apps: AppRecord[]
  /** If set, pre-filter to this pipeline */
  filterAppId?: string
}

export function GlobalRunsPanel({ apps, filterAppId }: Props) {
  const [traces, setTraces]     = useState<TraceRecord[]>([])
  const [loading, setLoading]   = useState(false)
  const [appFilter, setAppFilter] = useState(filterAppId ?? '')
  const [statusFilter, setStatusFilter] = useState<'all' | 'success' | 'error'>('all')
  const [expandedRun, setExpandedRun] = useState<string | null>(null)

  // Group traces by run_id
  const grouped = traces.reduce<Record<string, TraceRecord[]>>((acc, t) => {
    if (!acc[t.run_id]) acc[t.run_id] = []
    acc[t.run_id].push(t)
    return acc
  }, {})

  const runIds = Object.keys(grouped).sort((a, b) => {
    const aTime = grouped[a][0]?.created_at ?? ''
    const bTime = grouped[b][0]?.created_at ?? ''
    return bTime.localeCompare(aTime)
  })

  const filtered = statusFilter === 'all'
    ? runIds
    : runIds.filter((rid) => grouped[rid].some((t) => t.status === statusFilter))

  const fetchTraces = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams({ limit: '500' })
    if (appFilter) params.set('app_id', appFilter)
    fetch(`${API_BASE}/api/traces?${params}`)
      .then((r) => r.json())
      .then(setTraces)
      .catch(() => setTraces([]))
      .finally(() => setLoading(false))
  }, [appFilter])

  useEffect(() => { fetchTraces() }, [fetchTraces])

  const appName = (appId?: string) =>
    apps.find((a) => a.id === appId)?.name ?? appId ?? '—'

  return (
    <div className="ops-panel">
      {/* Toolbar */}
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">All Runs</span>
          <span className="ops-count-badge">{filtered.length} run{filtered.length !== 1 ? 's' : ''}</span>
        </div>
        <div className="ops-toolbar-right">
          <select
            className="ops-select"
            value={appFilter}
            onChange={(e) => setAppFilter(e.target.value)}
          >
            <option value="">All Pipelines</option>
            {apps.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
          <select
            className="ops-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as any)}
          >
            <option value="all">All Statuses</option>
            <option value="success">Success</option>
            <option value="error">Error</option>
          </select>
          <button type="button" className="ops-refresh-btn" onClick={fetchTraces} disabled={loading}>
            {loading ? 'Loading…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {/* Header row */}
      {filtered.length > 0 && (
        <div className="ops-table-header">
          <span className="ops-col-status" />
          <span className="ops-col-pipeline">Pipeline</span>
          <span className="ops-col-model">Model</span>
          <span className="ops-col-tokens">Tokens</span>
          <span className="ops-col-cost">Cost</span>
          <span className="ops-col-latency">Latency</span>
          <span className="ops-col-time">Time</span>
        </div>
      )}

      {/* Run list */}
      <div className="ops-list">
        {filtered.length === 0 && !loading && (
          <div className="ops-empty">No runs found. Execute a prompt to see run history here.</div>
        )}
        {filtered.map((runId) => {
          const spans = grouped[runId]
          const first = spans[0]
          const hasError = spans.some((s) => s.status === 'error')
          const totalTokens = spans.reduce((s, t) => s + t.total_tokens, 0)
          const totalCost   = spans.reduce((s, t) => s + t.cost_usd, 0)
          const maxLatency  = Math.max(...spans.map((t) => t.latency_ms))
          const isExpanded  = expandedRun === runId

          return (
            <div
              key={runId}
              className={`ops-run-row ${hasError ? 'ops-run-row--error' : 'ops-run-row--success'}`}
            >
              <div
                className="ops-run-summary"
                role="button"
                tabIndex={0}
                onClick={() => setExpandedRun(isExpanded ? null : runId)}
                onKeyDown={(e) => e.key === 'Enter' && setExpandedRun(isExpanded ? null : runId)}
              >
                <span className={`ops-status-dot ops-status-dot--${hasError ? 'error' : 'success'}`} />
                <span className="ops-col-pipeline" title={first.app_id}>{appName(first.app_id)}</span>
                <span className="ops-col-model">{first.provider}/{first.model}</span>
                <span className="ops-col-tokens">{totalTokens.toLocaleString()}</span>
                <span className="ops-col-cost">${totalCost.toFixed(5)}</span>
                <span className="ops-col-latency">{maxLatency}ms</span>
                <span className="ops-col-time">{new Date(first.created_at).toLocaleString()}</span>
                <span className="ops-expand-chevron">{isExpanded ? '▲' : '▼'}</span>
              </div>

              {isExpanded && (
                <div className="ops-run-spans">
                  {spans.map((span) => (
                    <div key={span.id} className={`ops-span-row ops-span-row--${span.status}`}>
                      <span className="ops-span-node">{span.node_type}</span>
                      <span className="ops-span-model">{span.provider}/{span.model}</span>
                      <span className="ops-span-tokens">↑{span.prompt_tokens} ↓{span.completion_tokens}</span>
                      <span className="ops-span-latency">{span.latency_ms}ms</span>
                      <span className="ops-span-status">{span.status}</span>
                      {span.error && <span className="ops-span-error">{span.error}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
