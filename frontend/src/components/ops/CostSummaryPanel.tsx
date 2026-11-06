import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../../types'
import { BudgetsPanel } from './BudgetsPanel'

interface AppRecord {
  id: string
  name: string
}

interface Props {
  apps: AppRecord[]
}

interface CostTotals {
  total_traces: number
  total_cost: number
  total_tokens: number
  total_prompt_tokens: number
  total_completion_tokens: number
  avg_latency_ms: number
  max_latency_ms: number
  error_count: number
  fallback_count: number
}

interface ModelRow {
  provider: string
  model: string
  traces: number
  cost_usd: number
  tokens: number
  avg_latency_ms: number
  errors: number
}

interface DailyRow {
  day: string
  cost_usd: number
  tokens: number
  traces: number
  errors: number
}

interface AppRow {
  app_id: string
  traces: number
  cost_usd: number
  tokens: number
  avg_latency_ms: number
}

interface SummaryData {
  days: number
  app_id: string | null
  totals: CostTotals
  by_model: ModelRow[]
  by_app: AppRow[]
  daily: DailyRow[]
}

export function CostSummaryPanel({ apps }: Props) {
  const [data, setData] = useState<SummaryData | null>(null)
  const [loading, setLoading] = useState(false)
  const [days, setDays] = useState(30)
  const [appFilter, setAppFilter] = useState('')

  const appName = (id: string) =>
    id === 'unassigned' ? '(no pipeline)' : (apps.find((a) => a.id === id)?.name ?? id)

  const fetchSummary = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams({ days: String(days) })
    if (appFilter) params.set('app_id', appFilter)
    fetch(`${API_BASE}/api/traces/cost-summary?${params}`)
      .then((r) => r.json())
      .then((d) => setData(d))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [days, appFilter])

  useEffect(() => { fetchSummary() }, [fetchSummary])

  const t = data?.totals
  const daily = data?.daily ?? []
  const byModel = data?.by_model ?? []
  const byApp = data?.by_app ?? []

  // Compute bar widths for daily chart
  const maxDailyCost = Math.max(...daily.map((d) => d.cost_usd ?? 0), 0.000001)
  const maxDailyTokens = Math.max(...daily.map((d) => d.tokens ?? 0), 1)
  // Model bar width
  const maxModelCost = Math.max(...byModel.map((m) => m.cost_usd ?? 0), 0.000001)

  return (
    <div className="ops-panel">
      {/* ── Toolbar ── */}
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">💰 Cost Summary</span>
        </div>
        <div className="ops-toolbar-right">
          <select className="ops-select" value={appFilter} onChange={(e) => setAppFilter(e.target.value)}>
            <option value="">All Pipelines</option>
            {apps.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
          <select className="ops-select" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <button type="button" className="ops-refresh-btn" onClick={fetchSummary} disabled={loading}>
            {loading ? '…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      <div style={{ padding: '14px 16px 0' }}>
        <BudgetsPanel apps={apps} />
      </div>

      {!data && !loading && (
        <div className="ops-empty">No trace data found for this period. Run a prompt to generate cost data.</div>
      )}

      {data && (
        <>
          {/* ── KPI ribbon ── */}
          <div className="ops-stats-bar">
            <div className="ops-stat">
              <span className="ops-stat-value">{t?.total_traces?.toLocaleString() ?? '—'}</span>
              <span className="ops-stat-label">Total Traces</span>
            </div>
            <div className="ops-stat">
              <span className="ops-stat-value" style={{ color: '#16a34a' }}>
                ${(t?.total_cost ?? 0).toFixed(5)}
              </span>
              <span className="ops-stat-label">Total Cost</span>
            </div>
            <div className="ops-stat">
              <span className="ops-stat-value">{(t?.total_tokens ?? 0).toLocaleString()}</span>
              <span className="ops-stat-label">Total Tokens</span>
            </div>
            <div className="ops-stat">
              <span className="ops-stat-value">
                {(t?.total_prompt_tokens ?? 0).toLocaleString()}
              </span>
              <span className="ops-stat-label">Prompt Tokens</span>
            </div>
            <div className="ops-stat">
              <span className="ops-stat-value">
                {(t?.total_completion_tokens ?? 0).toLocaleString()}
              </span>
              <span className="ops-stat-label">Completion Tokens</span>
            </div>
            <div className="ops-stat">
              <span className="ops-stat-value">{Math.round(t?.avg_latency_ms ?? 0)}ms</span>
              <span className="ops-stat-label">Avg Latency</span>
            </div>
            <div className="ops-stat">
              <span className="ops-stat-value" style={{ color: (t?.error_count ?? 0) > 0 ? '#dc2626' : undefined }}>
                {t?.error_count ?? 0}
              </span>
              <span className="ops-stat-label">Errors</span>
            </div>
          </div>

          {/* ── Daily cost bar chart ── */}
          {daily.length > 0 && (
            <div className="cost-card">
              <div className="cost-card-title">Daily Cost &amp; Token Usage</div>
              <div className="cost-daily-chart">
                {daily.map((row) => (
                  <div key={row.day} className="cost-daily-col">
                    <div className="cost-daily-bars">
                      {/* cost bar */}
                      <div
                        className="cost-daily-bar cost-bar"
                        style={{ height: `${Math.max(2, Math.round((row.cost_usd / maxDailyCost) * 80))}px` }}
                        title={`Cost: $${row.cost_usd.toFixed(5)}`}
                      />
                      {/* token bar (secondary, lighter) */}
                      <div
                        className="cost-daily-bar token-bar"
                        style={{ height: `${Math.max(1, Math.round((row.tokens / maxDailyTokens) * 80))}px` }}
                        title={`Tokens: ${row.tokens.toLocaleString()}`}
                      />
                    </div>
                    <div className="cost-daily-label">{row.day.slice(5)}</div>
                    {row.errors > 0 && <div className="cost-daily-error-dot" title={`${row.errors} error(s)`} />}
                  </div>
                ))}
              </div>
              <div className="cost-daily-legend">
                <span className="cost-legend-dot cost" /> Cost (USD)
                <span className="cost-legend-dot token" style={{ marginLeft: 16 }} /> Tokens
              </div>
            </div>
          )}

          {/* ── By model table ── */}
          {byModel.length > 0 && (
            <div className="cost-card">
              <div className="cost-card-title">Cost by Model</div>
              <div className="cost-model-list">
                {byModel.map((row, idx) => {
                  const barPct = Math.max(2, Math.round((row.cost_usd / maxModelCost) * 100))
                  return (
                    <div key={idx} className="cost-model-row">
                      <div className="cost-model-meta">
                        <span className="cost-model-name mono">{row.provider}/{row.model}</span>
                        <span className="cost-model-traces">{row.traces} traces</span>
                        {row.errors > 0 && (
                          <span className="cost-model-errors">⚠ {row.errors} err</span>
                        )}
                      </div>
                      <div className="cost-model-bar-row">
                        <div className="cost-model-track">
                          <div className="cost-model-bar" style={{ width: `${barPct}%` }} />
                        </div>
                        <span className="cost-model-cost">${row.cost_usd.toFixed(5)}</span>
                      </div>
                      <div className="cost-model-stats">
                        <span>{row.tokens.toLocaleString()} tokens</span>
                        <span>{Math.round(row.avg_latency_ms)}ms avg</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ── By pipeline table (only shown without app filter) ── */}
          {byApp.length > 0 && !appFilter && (
            <div className="cost-card">
              <div className="cost-card-title">Cost by Pipeline</div>
              <div className="cost-model-list">
                {byApp.map((row, idx) => {
                  const maxAppCost = Math.max(...byApp.map((a) => a.cost_usd ?? 0), 0.000001)
                  const barPct = Math.max(2, Math.round((row.cost_usd / maxAppCost) * 100))
                  return (
                    <div key={idx} className="cost-model-row">
                      <div className="cost-model-meta">
                        <span className="cost-model-name">{appName(row.app_id)}</span>
                        <span className="cost-model-traces">{row.traces} traces</span>
                      </div>
                      <div className="cost-model-bar-row">
                        <div className="cost-model-track">
                          <div className="cost-model-bar" style={{ width: `${barPct}%`, background: '#6366f1' }} />
                        </div>
                        <span className="cost-model-cost">${row.cost_usd.toFixed(5)}</span>
                      </div>
                      <div className="cost-model-stats">
                        <span>{row.tokens.toLocaleString()} tokens</span>
                        <span>{Math.round(row.avg_latency_ms)}ms avg</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
