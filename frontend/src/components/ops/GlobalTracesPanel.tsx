import { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import { API_BASE, type TraceRecord } from '../../types'
import { TraceDetailDrawer } from '../TraceDetailDrawer'
import { isSimulated } from '../../utils/traceFlags'

interface AppRecord {
  id: string
  name: string
}

interface Props {
  apps: AppRecord[]
  filterAppId?: string
}

type SortField = 'time_desc' | 'time_asc' | 'latency_desc' | 'cost_desc' | 'tokens_desc'

export function GlobalTracesPanel({ apps, filterAppId }: Props) {
  const [traces, setTraces] = useState<TraceRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedTrace, setSelectedTrace] = useState<TraceRecord | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [appFilter, setAppFilter] = useState(filterAppId ?? '')
  const [statusFilter, setStatusFilter] = useState<'all' | 'success' | 'error' | 'fallback'>('all')
  const [modelFilter, setModelFilter] = useState('')
  const [sortField, setSortField] = useState<SortField>('time_desc')
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchTraces = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams({ limit: '1000' })
    if (appFilter) params.set('app_id', appFilter)
    fetch(`${API_BASE}/api/traces?${params}`)
      .then((r) => r.json())
      .then((data) => setTraces(Array.isArray(data) ? data : []))
      .catch(() => setTraces([]))
      .finally(() => setLoading(false))
  }, [appFilter])

  useEffect(() => {
    fetchTraces()
  }, [fetchTraces])

  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(fetchTraces, 5000)
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [autoRefresh, fetchTraces])

  const clearTraces = () => {
    if (!window.confirm('Clear all trace records? This cannot be undone.')) return
    fetch(`${API_BASE}/api/traces`, { method: 'DELETE' }).then(() => {
      setTraces([])
      setSelectedTrace(null)
    })
  }

  const appName = (appId?: string) =>
    apps.find((a) => a.id === appId)?.name ?? appId ?? '—'

  const models = Array.from(
    new Set(traces.map((t) => `${t.provider}/${t.model}`)),
  ).filter(Boolean).sort()

  // Filter & Search
  const filtered = useMemo(() => {
    let result = traces.filter((t) => {
      if (statusFilter === 'success' && t.status !== 'success') return false
      if (statusFilter === 'error' && t.status !== 'error') return false
      if (statusFilter === 'fallback') {
        const isFb = Boolean(t.used_fallback && Number(t.used_fallback) > 0)
        if (!isFb) return false
      }
      if (modelFilter && `${t.provider}/${t.model}` !== modelFilter) return false
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim()
        const matchRun = t.run_id?.toLowerCase().includes(q)
        const matchTrace = t.id?.toLowerCase().includes(q)
        const matchModel = `${t.provider}/${t.model}`.toLowerCase().includes(q)
        const matchError = t.error?.toLowerCase().includes(q)
        const matchPrompt = t.prompt_preview?.toLowerCase().includes(q)
        const matchApp = appName(t.app_id).toLowerCase().includes(q)
        if (!matchRun && !matchTrace && !matchModel && !matchError && !matchPrompt && !matchApp) {
          return false
        }
      }
      return true
    })

    // Sort
    result.sort((a, b) => {
      if (sortField === 'time_desc') return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      if (sortField === 'time_asc') return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      if (sortField === 'latency_desc') return b.latency_ms - a.latency_ms
      if (sortField === 'cost_desc') return b.cost_usd - a.cost_usd
      if (sortField === 'tokens_desc') return b.total_tokens - a.total_tokens
      return 0
    })

    return result
  }, [traces, statusFilter, modelFilter, searchQuery, sortField, apps])

  // Aggregates
  const totalCost = filtered.reduce((s, t) => s + (t.cost_usd || 0), 0)
  const totalTokens = filtered.reduce((s, t) => s + (t.total_tokens || 0), 0)
  const avgLatency = filtered.length
    ? Math.round(filtered.reduce((s, t) => s + t.latency_ms, 0) / filtered.length)
    : 0

  // P95 Latency
  const sortedLatencies = [...filtered.map((t) => t.latency_ms)].sort((a, b) => a - b)
  const p95Latency = sortedLatencies.length
    ? sortedLatencies[Math.floor(sortedLatencies.length * 0.95)]
    : 0

  const errorCount = filtered.filter((t) => t.status === 'error').length
  const fallbackCount = filtered.filter((t) => Number(t.used_fallback) > 0).length
  const successRate = filtered.length
    ? Math.round(((filtered.length - errorCount) / filtered.length) * 100)
    : 100

  const maxLatency = Math.max(...filtered.map((t) => t.latency_ms), 1)

  const copyId = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    navigator.clipboard.writeText(id).then(() => {
      setCopiedId(id)
      setTimeout(() => setCopiedId(null), 1500)
    })
  }

  const exportAllJSON = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(filtered, null, 2))
    const downloadAnchor = document.createElement('a')
    downloadAnchor.setAttribute('href', dataStr)
    downloadAnchor.setAttribute('download', `traces-export-${new Date().toISOString().slice(0, 10)}.json`)
    document.body.appendChild(downloadAnchor)
    downloadAnchor.click()
    downloadAnchor.remove()
  }

  const exportCSV = () => {
    const headers = ['id', 'run_id', 'app_id', 'node_type', 'provider', 'model', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'latency_ms', 'cost_usd', 'status', 'created_at']
    const rows = filtered.map((t) => [
      t.id,
      t.run_id,
      t.app_id || '',
      t.node_type,
      t.provider,
      t.model,
      t.prompt_tokens,
      t.completion_tokens,
      t.total_tokens,
      t.latency_ms,
      t.cost_usd,
      t.status,
      t.created_at,
    ])
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map((e) => e.join(','))].join('\n')
    const encodedUri = encodeURI(csvContent)
    const link = document.createElement('a')
    link.setAttribute('href', encodedUri)
    link.setAttribute('download', `traces-${new Date().toISOString().slice(0, 10)}.csv`)
    document.body.appendChild(link)
    link.click()
    link.remove()
  }

  // Get all spans for currently selected trace's run
  const relatedRunTraces = useMemo(() => {
    if (!selectedTrace) return []
    return traces.filter((t) => t.run_id === selectedTrace.run_id)
  }, [traces, selectedTrace])

  return (
    <div className="ops-panel">
      {/* ── 1. Summary KPI ribbon ── */}
      <div className="ops-stats-bar">
        <div className="ops-stat">
          <span className="ops-stat-value">{filtered.length > 0 ? filtered.length.toLocaleString() : '—'}</span>
          <span className="ops-stat-label">Total Traces</span>
        </div>
        <div className="ops-stat">
          <span className="ops-stat-value" style={{ color: successRate >= 95 ? '#16a34a' : '#d97706' }}>
            {filtered.length > 0 ? `${successRate}%` : '—'}
          </span>
          <span className="ops-stat-label">Success Rate</span>
        </div>
        <div className="ops-stat">
          <span className="ops-stat-value">{filtered.length > 0 ? totalTokens.toLocaleString() : '—'}</span>
          <span className="ops-stat-label">Total Tokens</span>
        </div>
        <div className="ops-stat">
          <span className="ops-stat-value">{filtered.length > 0 ? `$${totalCost.toFixed(5)}` : '—'}</span>
          <span className="ops-stat-label">Total Cost</span>
        </div>
        <div className="ops-stat">
          <span className="ops-stat-value">{filtered.length > 0 ? `${avgLatency}ms` : '—'}</span>
          <span className="ops-stat-label">Avg Latency</span>
        </div>
        <div className="ops-stat">
          <span className="ops-stat-value">{filtered.length > 0 ? `${p95Latency}ms` : '—'}</span>
          <span className="ops-stat-label">P95 Latency</span>
        </div>
        <div className="ops-stat">
          <span className={`ops-stat-value ${errorCount > 0 ? 'ops-stat-value--error' : ''}`}>
            {filtered.length > 0 ? errorCount : '—'}
          </span>
          <span className="ops-stat-label">Errors</span>
        </div>
        {fallbackCount > 0 && (
          <div className="ops-stat">
            <span className="ops-stat-value" style={{ color: '#d97706' }}>{fallbackCount}</span>
            <span className="ops-stat-label">Fallbacks</span>
          </div>
        )}
      </div>

      {/* ── 2. Toolbar — Search + Filters + Actions ── */}
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">All Traces</span>
          <span className="ops-count-badge">
            {filtered.length} {filtered.length === 1 ? 'trace' : 'traces'}
          </span>
          <div className="ops-search-box">
            <input
              type="text"
              placeholder="Search by run ID, model, prompt, error…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="ops-search-input"
            />
            {searchQuery && (
              <button type="button" className="ops-search-clear" onClick={() => setSearchQuery('')}>
                ✕
              </button>
            )}
          </div>
        </div>

        <div className="ops-toolbar-right">
          <select className="ops-select" value={appFilter} onChange={(e) => setAppFilter(e.target.value)}>
            <option value="">All Pipelines</option>
            {apps.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>

          <select
            className="ops-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as any)}
          >
            <option value="all">All Statuses</option>
            <option value="success">Success</option>
            <option value="error">Errors Only</option>
            <option value="fallback">Fallbacks Only (⇄)</option>
          </select>

          <select className="ops-select" value={modelFilter} onChange={(e) => setModelFilter(e.target.value)}>
            <option value="">All Models</option>
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>

          <select className="ops-select" value={sortField} onChange={(e) => setSortField(e.target.value as SortField)}>
            <option value="time_desc">Newest First</option>
            <option value="time_asc">Oldest First</option>
            <option value="latency_desc">Highest Latency</option>
            <option value="cost_desc">Highest Cost</option>
            <option value="tokens_desc">Most Tokens</option>
          </select>

          <label className="ops-live-label" title="Automatically refresh traces every 5 seconds">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            <span className={`live-pulse-dot ${autoRefresh ? 'active' : ''}`} />
            Live
          </label>

          <button type="button" className="ops-refresh-btn" onClick={fetchTraces} disabled={loading} title="Refresh traces">
            {loading ? '…' : '↻ Refresh'}
          </button>

          <button type="button" className="ops-export-btn" onClick={exportAllJSON} disabled={filtered.length === 0} title="Export filtered traces to JSON">
            ↓ JSON
          </button>

          <button type="button" className="ops-export-btn" onClick={exportCSV} disabled={filtered.length === 0} title="Export filtered traces to CSV">
            ↓ CSV
          </button>

          <button type="button" className="ops-danger-btn" onClick={clearTraces} disabled={traces.length === 0}>
            Clear All
          </button>
        </div>
      </div>

      {/* ── 3. Table Header ── */}
      {filtered.length > 0 && (
        <div className="ops-table-header">
          <span className="ops-col-status" />
          <span className="ops-col-pipeline">Pipeline / App</span>
          <span className="ops-col-model">Model</span>
          <span className="ops-col-run">Run ID</span>
          <span className="ops-col-tokens">Tokens (↑in ↓out =tot)</span>
          <span className="ops-col-cost">Cost</span>
          <span className="ops-col-latency">Latency</span>
          <span className="ops-col-time">Time</span>
          <span className="ops-col-actions">Actions</span>
        </div>
      )}

      {/* ── 4. Trace Rows List ── */}
      <div className="ops-list">
        {filtered.length === 0 && !loading && (
          <div className="ops-empty">
            {traces.length === 0
              ? 'No traces found. Execute a prompt in the canvas to generate execution traces.'
              : 'No traces match the selected filters or search query.'}
          </div>
        )}

        {filtered.map((t) => {
          const isSelected = selectedTrace?.id === t.id
          const isFallback = Boolean(t.used_fallback && Number(t.used_fallback) > 0)
          const latencyPct = Math.min(100, Math.max(5, Math.round((t.latency_ms / maxLatency) * 100)))
          const latencyColor = t.latency_ms > 3000 ? '#ef4444' : t.latency_ms > 1000 ? '#f59e0b' : '#22c55e'

          return (
            <div
              key={t.id}
              className={`ops-trace-row ops-trace-row--${t.status} ${isSelected ? 'ops-trace-row--selected' : ''}`}
              onClick={() => setSelectedTrace(t)}
            >
              <span
                className={`ops-status-dot ops-status-dot--${t.status}`}
                title={t.status === 'success' ? 'Successful Execution' : 'Execution Failed'}
              />

              <span className="ops-col-pipeline" title={appName(t.app_id)}>
                <span className="pipeline-badge">{appName(t.app_id)}</span>
              </span>

              <span className="ops-col-model" title={`${t.provider}/${t.model}`}>
                <span className="model-chip">
                  {t.provider}/{t.model}
                </span>
                {isFallback && <span className="trace-tag-fallback" title="Fallback model invoked">⇄</span>}
                {isSimulated(t) && <span className="trace-tag-sim-mini" title="Simulated: no model was called (mock provider or no API key)">sim</span>}
              </span>

              <span className="ops-col-run mono" onClick={(e) => copyId(t.run_id, e)} title="Click to copy Run ID">
                {t.run_id.slice(0, 8)}…
                {copiedId === t.run_id && <span className="copied-pill">copied</span>}
              </span>

              <div className="ops-col-tokens ops-token-detail">
                <span className="tok-prompt" title="Prompt Tokens">↑{t.prompt_tokens}</span>
                <span className="tok-comp" title="Completion Tokens">↓{t.completion_tokens}</span>
                <span className="ops-token-total" title="Total Tokens">={t.total_tokens}</span>
              </div>

              <span className="ops-col-cost font-semibold">${t.cost_usd.toFixed(5)}</span>

              <div className="ops-col-latency">
                <div className="latency-bar-container">
                  <div className="latency-bar-track">
                    <div className="latency-bar-fill" style={{ width: `${latencyPct}%`, background: latencyColor }} />
                  </div>
                  <span className="latency-text">{t.latency_ms >= 1000 ? `${(t.latency_ms / 1000).toFixed(2)}s` : `${t.latency_ms}ms`}</span>
                </div>
              </div>

              <span className="ops-col-time">{new Date(t.created_at).toLocaleTimeString()}</span>

              <div className="ops-col-actions" onClick={(e) => e.stopPropagation()}>
                <button
                  type="button"
                  className="ops-row-inspect-btn"
                  onClick={() => setSelectedTrace(t)}
                  title="Inspect trace details"
                >
                  Inspect 🔍
                </button>
              </div>

              {t.error && (
                <div className="ops-trace-error" title={t.error}>
                  <span className="error-icon">⚠</span> {t.error.slice(0, 140)}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* ── 5. Detail Slide-Over Drawer ── */}
      {selectedTrace && (
        <TraceDetailDrawer
          trace={selectedTrace}
          allRunTraces={relatedRunTraces}
          appName={appName(selectedTrace.app_id)}
          onClose={() => setSelectedTrace(null)}
        />
      )}
    </div>
  )
}
