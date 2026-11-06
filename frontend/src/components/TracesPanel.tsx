import { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import { API_BASE, type TraceRecord } from '../types'
import { TraceDetailDrawer } from './TraceDetailDrawer'
import { isSimulated } from '../utils/traceFlags'

type ViewMode = 'timeline' | 'cost' | 'failures'

function groupByRun(traces: TraceRecord[]): Map<string, TraceRecord[]> {
  const map = new Map<string, TraceRecord[]>()
  for (const t of traces) {
    const arr = map.get(t.run_id) ?? []
    arr.push(t)
    map.set(t.run_id, arr)
  }
  return map
}

function fmt(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`
}

function fmtCost(c: number) {
  return c === 0 ? '$0.00000' : `$${c.toFixed(5)}`
}

function latencyBar(ms: number, maxMs: number) {
  const pct = maxMs > 0 ? Math.min(100, Math.max(6, Math.round((ms / maxMs) * 100))) : 0
  const color = ms > 3000 ? '#ef4444' : ms > 1000 ? '#f59e0b' : '#22c55e'
  return { pct, color }
}

export function TracesPanel() {
  const [traces, setTraces] = useState<TraceRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [view, setView] = useState<ViewMode>('timeline')
  const [expandedRun, setExpandedRun] = useState<string | null>(null)
  const [selectedTrace, setSelectedTrace] = useState<TraceRecord | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchTraces = useCallback(() => {
    setLoading(true)
    fetch(`${API_BASE}/api/traces?limit=300`)
      .then((r) => r.json())
      .then((data) => setTraces(Array.isArray(data) ? data : []))
      .catch(() => setTraces([]))
      .finally(() => setLoading(false))
  }, [])

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
    if (!window.confirm('Clear all trace records?')) return
    fetch(`${API_BASE}/api/traces`, { method: 'DELETE' }).then(() => {
      setTraces([])
      setSelectedTrace(null)
    })
  }

  // ── Filter by search query ──────────────────────────────────────────────────
  const filteredTraces = useMemo(() => {
    if (!searchQuery.trim()) return traces
    const q = searchQuery.toLowerCase().trim()
    return traces.filter((t) => {
      return (
        t.run_id?.toLowerCase().includes(q) ||
        t.model?.toLowerCase().includes(q) ||
        t.provider?.toLowerCase().includes(q) ||
        t.error?.toLowerCase().includes(q) ||
        t.node_type?.toLowerCase().includes(q)
      )
    })
  }, [traces, searchQuery])

  // ── Aggregates ──────────────────────────────────────────────────────────────
  const totalRuns = traces.length
  const successRuns = traces.filter((t) => t.status === 'success').length
  const errorRuns = traces.filter((t) => t.status === 'error').length
  const totalCost = traces.reduce((s, t) => s + (t.cost_usd || 0), 0)
  const totalTokens = traces.reduce((s, t) => s + (t.total_tokens || 0), 0)
  const avgLatency =
    totalRuns > 0 ? Math.round(traces.reduce((s, t) => s + t.latency_ms, 0) / totalRuns) : 0
  const fallbackRuns = traces.filter((t) => Number(t.used_fallback) > 0).length

  const grouped = useMemo(() => groupByRun(filteredTraces), [filteredTraces])
  const runIds = Array.from(grouped.keys())

  const maxRunLatency = useMemo(() => {
    if (runIds.length === 0) return 1
    return Math.max(
      ...runIds.map((rid) => {
        const sp = grouped.get(rid) || []
        return sp.reduce((s, t) => s + t.latency_ms, 0)
      }),
      1,
    )
  }, [grouped, runIds])

  const failures = traces.filter((t) => t.status === 'error')

  // ── Cost breakdown by model ──────────────────────────────────────────────────
  const costByModel: Record<string, { cost: number; count: number; tokens: number }> = {}
  for (const t of traces) {
    const key = `${t.provider}/${t.model}`
    if (!costByModel[key]) costByModel[key] = { cost: 0, count: 0, tokens: 0 }
    costByModel[key].cost += t.cost_usd || 0
    costByModel[key].count++
    costByModel[key].tokens += t.total_tokens || 0
  }
  const costRows = Object.entries(costByModel).sort((a, b) => b[1].cost - a[1].cost)

  // Spans for currently selected trace's run
  const relatedRunTraces = useMemo(() => {
    if (!selectedTrace) return []
    return traces.filter((t) => t.run_id === selectedTrace.run_id)
  }, [traces, selectedTrace])

  return (
    <div className="traces-panel-body">
      {/* ── 1. KPI summary ribbon ── */}
      <div className="obs-kpi-row">
        <div className="obs-kpi">
          <div className="obs-kpi-value">{totalRuns > 0 ? totalRuns : '—'}</div>
          <div className="obs-kpi-label">Runs</div>
        </div>
        <div className="obs-kpi">
          <div className="obs-kpi-value" style={{ color: totalRuns > 0 ? '#16a34a' : '#94a3b8' }}>
            {totalRuns > 0 ? successRuns : '—'}
          </div>
          <div className="obs-kpi-label">Success</div>
        </div>
        <div className="obs-kpi">
          <div className="obs-kpi-value" style={{ color: errorRuns > 0 ? '#dc2626' : '#94a3b8' }}>
            {totalRuns > 0 ? errorRuns : '—'}
          </div>
          <div className="obs-kpi-label">Errors</div>
        </div>
        <div className="obs-kpi">
          <div className="obs-kpi-value">{totalRuns > 0 ? fmt(avgLatency) : '—'}</div>
          <div className="obs-kpi-label">Avg Latency</div>
        </div>
        <div className="obs-kpi">
          <div className="obs-kpi-value">{totalRuns > 0 ? fmtCost(totalCost) : '—'}</div>
          <div className="obs-kpi-label">Total Cost</div>
        </div>
        <div className="obs-kpi">
          <div className="obs-kpi-value">{totalRuns > 0 ? `${(totalTokens / 1000).toFixed(1)}k` : '—'}</div>
          <div className="obs-kpi-label">Tokens</div>
        </div>
        {fallbackRuns > 0 && (
          <div className="obs-kpi">
            <div className="obs-kpi-value" style={{ color: '#d97706' }}>
              {fallbackRuns}
            </div>
            <div className="obs-kpi-label">Fallbacks</div>
          </div>
        )}
      </div>

      {/* ── 2. Tab bar + Search & Toolbar controls ── */}
      <div className="obs-tab-toolbar">
        <div className="obs-view-tabs-inline">
          {(['timeline', 'cost', 'failures'] as ViewMode[]).map((v) => (
            <button
              key={v}
              type="button"
              className={`obs-view-tab ${view === v ? 'active' : ''}`}
              onClick={() => setView(v)}
            >
              {v === 'timeline'
                ? '⏱ Timeline'
                : v === 'cost'
                ? '💰 Cost'
                : `🚨 Failures${failures.length > 0 ? ` (${failures.length})` : ''}`}
            </button>
          ))}
        </div>
        <div className="obs-toolbar-controls">
          <button
            type="button"
            className="traces-refresh-btn"
            disabled={loading}
            onClick={fetchTraces}
            title="Refresh traces"
          >
            {loading ? '…' : '↻'}
          </button>
          <label className="traces-auto-label" title="Live refresh every 5 seconds">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            Live
          </label>
          <button
            type="button"
            className="traces-clear-btn"
            onClick={clearTraces}
            disabled={totalRuns === 0}
            title="Clear all traces"
          >
            Clear
          </button>
        </div>
      </div>

      {/* ── Search Bar inside sidebar ── */}
      {totalRuns > 0 && (
        <div className="obs-sidebar-search">
          <input
            type="text"
            placeholder="Filter runs by ID, model, error…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="obs-sidebar-search-input"
          />
          {searchQuery && (
            <button type="button" className="obs-sidebar-search-clear" onClick={() => setSearchQuery('')}>
              ✕
            </button>
          )}
        </div>
      )}

      {/* ── 3. Empty state ── */}
      {totalRuns === 0 && !loading && (
        <div className="traces-empty">
          No traces yet. Run a prompt in the canvas to see the observability timeline here.
        </div>
      )}

      {/* ── TIMELINE VIEW ── */}
      {view === 'timeline' && totalRuns > 0 && (
        <div className="obs-timeline">
          {runIds.length === 0 && searchQuery && (
            <div className="traces-empty">No traces matched &ldquo;{searchQuery}&rdquo;.</div>
          )}

          {runIds.map((runId) => {
            const spans = grouped.get(runId) || []
            const runSuccess = spans.every((s) => s.status === 'success')
            const runLatency = spans.reduce((s, t) => s + t.latency_ms, 0)
            const runCost = spans.reduce((s, t) => s + (t.cost_usd || 0), 0)
            const runTokens = spans.reduce((s, t) => s + (t.total_tokens || 0), 0)
            const ts = spans[0]?.created_at
            const isExpanded = expandedRun === runId
            const { pct, color } = latencyBar(runLatency, maxRunLatency)
            const hasFallback = spans.some((s) => Number(s.used_fallback) > 0)
            const simulated = spans.some(isSimulated)

            return (
              <div key={runId} className={`obs-run-row ${runSuccess ? '' : 'obs-run-error'}`}>
                <div
                  className="obs-run-header"
                  onClick={() => setExpandedRun(isExpanded ? null : runId)}
                >
                  <span
                    className="obs-run-dot"
                    style={{ color: runSuccess ? '#22c55e' : '#ef4444' }}
                    title={runSuccess ? 'Run Succeeded' : 'Run Failed'}
                  >
                    {runSuccess ? '●' : '✕'}
                  </span>
                  <span className="obs-run-id mono">{runId.slice(0, 8)}…</span>
                  <span className="obs-run-time">{ts ? new Date(ts).toLocaleTimeString() : ''}</span>

                  <div className="obs-run-bar-wrap">
                    <div className="obs-run-bar" style={{ width: `${pct}%`, background: color }} />
                  </div>

                  {hasFallback && <span className="trace-tag-fallback-mini" title="Fallback used">⇄</span>}
                  {simulated && <span className="trace-tag-sim-mini" title="Simulated: no model was called">sim</span>}

                  <span className="obs-run-latency">{fmt(runLatency)}</span>
                  <span className="obs-run-cost">{fmtCost(runCost)}</span>
                  <span className="obs-run-chevron">{isExpanded ? '▲' : '▼'}</span>
                </div>

                {isExpanded && (
                  <div className="obs-run-spans">
                    {spans.map((span) => (
                      <div
                        key={span.id}
                        className={`obs-span-row obs-span--${span.status}`}
                        onClick={() => setSelectedTrace(span)}
                      >
                        <span className="obs-span-dot">{span.status === 'success' ? '○' : '✕'}</span>
                        <span className="obs-span-type">{span.node_type}</span>
                        <span className="obs-span-model mono">{span.provider}/{span.model}</span>
                        <span className="obs-span-tokens">
                          ↑{span.prompt_tokens} ↓{span.completion_tokens}
                        </span>
                        <span className="obs-span-latency">{fmt(span.latency_ms)}</span>
                        <span className="obs-span-cost">{fmtCost(span.cost_usd)}</span>

                        {isSimulated(span) && (
                          <span className="obs-span-sim" title="Simulated: no model was called (mock provider or no API key)">
                            simulated
                          </span>
                        )}
                        {span.used_fallback && Number(span.used_fallback) > 0 && (
                          <span
                            className="obs-span-fallback"
                            title={`Fallback: ${span.effective_provider}/${span.effective_model}`}
                          >
                            ⇄ fallback
                          </span>
                        )}

                        <button
                          type="button"
                          className="obs-span-inspect-btn"
                          onClick={(e) => {
                            e.stopPropagation()
                            setSelectedTrace(span)
                          }}
                          title="Inspect trace details"
                        >
                          🔍
                        </button>

                        {span.error && <div className="obs-span-error">{span.error}</div>}
                      </div>
                    ))}
                    <div className="obs-span-summary">
                      <button
                        type="button"
                        className="obs-run-inspect-all-btn"
                        onClick={() => setSelectedTrace(spans[0])}
                      >
                        Inspect Full Run 🔍
                      </button>
                      <span>
                        ∑ {runTokens.toLocaleString()} tokens · {fmtCost(runCost)} · {spans.length} span
                        {spans.length !== 1 ? 's' : ''}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* ── COST VIEW ── */}
      {view === 'cost' && totalRuns > 0 && (
        <div className="obs-cost-view">
          <div className="obs-cost-total">
            <div style={{ fontSize: 22, fontWeight: 800, color: '#0f172a' }}>{fmtCost(totalCost)}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>
              total across {totalRuns} runs · {(totalTokens / 1000).toFixed(1)}k tokens
            </div>
          </div>
          <table className="obs-cost-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Runs</th>
                <th>Tokens</th>
                <th>Cost</th>
                <th>% of total</th>
              </tr>
            </thead>
            <tbody>
              {costRows.map(([model, stats]) => {
                const pct = totalCost > 0 ? Math.round((stats.cost / totalCost) * 100) : 0
                return (
                  <tr key={model}>
                    <td className="obs-cost-model mono">{model}</td>
                    <td>{stats.count}</td>
                    <td>{stats.tokens.toLocaleString()}</td>
                    <td style={{ fontWeight: 700 }}>{fmtCost(stats.cost)}</td>
                    <td>
                      <div className="obs-cost-bar-wrap">
                        <div className="obs-cost-bar" style={{ width: `${pct}%` }} />
                        <span>{pct}%</span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── FAILURES VIEW ── */}
      {view === 'failures' && (
        <div className="obs-failures">
          {failures.length === 0 ? (
            <div className="traces-empty" style={{ color: '#16a34a' }}>
              ✅ No failures — all runs succeeded
            </div>
          ) : (
            failures.map((t) => (
              <div
                key={t.id}
                className="obs-failure-row"
                onClick={() => setSelectedTrace(t)}
              >
                <div className="obs-failure-header">
                  <span style={{ color: '#ef4444', fontWeight: 700 }}>✕ Error</span>
                  <span className="obs-span-model mono">
                    {t.provider}/{t.model}
                  </span>
                  <span className="obs-span-latency">{fmt(t.latency_ms)}</span>
                  <span className="obs-run-time">{new Date(t.created_at).toLocaleTimeString()}</span>
                  <span className="obs-run-id mono">run:{t.run_id.slice(0, 8)}</span>
                  <button
                    type="button"
                    className="obs-span-inspect-btn"
                    onClick={(e) => {
                      e.stopPropagation()
                      setSelectedTrace(t)
                    }}
                    title="Inspect failure"
                  >
                    🔍 Inspect
                  </button>
                </div>
                <div className="obs-failure-msg">{t.error || 'Unknown error'}</div>
              </div>
            ))
          )}
        </div>
      )}

      {/* ── Slide-over Detail Drawer ── */}
      {selectedTrace && (
        <TraceDetailDrawer
          trace={selectedTrace}
          allRunTraces={relatedRunTraces}
          onClose={() => setSelectedTrace(null)}
        />
      )}
    </div>
  )
}
