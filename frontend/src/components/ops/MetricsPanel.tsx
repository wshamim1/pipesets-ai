import { useCallback, useEffect, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { API_BASE } from '../../types'

interface AppOption { id: string; name: string }

interface Point { t: string; runs: number; failed: number; p95_ms: number | null; cost_usd: number; tokens: number }

export interface MetricsOverview {
  hours: number
  bucket_seconds: number
  truncated: boolean
  totals: {
    runs: number; failed: number; error_rate: number | null; p50_ms: number | null; p95_ms: number | null
    cost_usd: number; tokens: number; simulated: number
  }
  series: Point[]
  models: { provider: string; model: string; runs: number; failed: number; p95_ms: number | null; cost_usd: number; tokens: number }[]
  tools: { name: string; calls: number; failed: number; p95_ms: number | null }[]
  phases: { phase: string; count: number; p95_ms: number | null; total_ms: number }[]
  agent_runs: { total: number; by_status: Record<string, number> }
  queue: { queued: number; running: number; dead: number; oldest_wait_s: number }
}

const WINDOWS = [
  { hours: 1, label: 'Last hour' },
  { hours: 6, label: 'Last 6 hours' },
  { hours: 24, label: 'Last 24 hours' },
  { hours: 168, label: 'Last 7 days' },
  { hours: 720, label: 'Last 30 days' },
]

const ms = (v: number | null | undefined) =>
  v == null ? '—' : v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}s` : `${v}ms`
const usd = (v: number) => (v >= 1 ? `$${v.toFixed(2)}` : v > 0 ? `$${v.toFixed(4)}` : '$0')
const pct = (v: number | null) => (v == null ? '—' : `${(v * 100).toFixed(v > 0 && v < 0.01 ? 1 : 0)}%`)
const wait = (s: number) => (s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${(s / 3600).toFixed(1)}h`)

/** Bucket start → "14:00" within a day, "Mon 14:00" / "Oct 31" beyond it. */
function bucketLabel(iso: string, hours: number): string {
  const d = new Date(iso)
  if (hours <= 24) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (hours <= 168) return d.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const W = 600   // SVG user units; the chart scales to its container
const H = 160

/** Index of the bucket under the pointer. */
function bucketAt(e: ReactPointerEvent<SVGSVGElement>, n: number): number {
  const box = e.currentTarget.getBoundingClientRect()
  return Math.min(n - 1, Math.max(0, Math.floor(((e.clientX - box.left) / box.width) * n)))
}

function Tooltip({ x, n, children }: { x: number; n: number; children: React.ReactNode }) {
  const left = ((x + 0.5) / n) * 100
  return (
    <div className="mx-tooltip" role="status" style={left > 60 ? { right: `${100 - left}%` } : { left: `${left}%` }}>
      {children}
    </div>
  )
}

function Axis({ series, hours, max, fmt }: { series: Point[]; hours: number; max: number; fmt: (v: number) => string }) {
  const mid = Math.floor(series.length / 2)
  return (
    <>
      <span className="mx-axis-y mx-axis-top">{fmt(max)}</span>
      <span className="mx-axis-y mx-axis-zero">0</span>
      <div className="mx-axis-x">
        <span>{bucketLabel(series[0].t, hours)}</span>
        <span>{bucketLabel(series[mid].t, hours)}</span>
        <span>{bucketLabel(series[series.length - 1].t, hours)}</span>
      </div>
    </>
  )
}

/** Runs per bucket: succeeded and failed stacked, with a 2px gap between them. */
function RunsChart({ series, hours }: { series: Point[]; hours: number }) {
  const [hover, setHover] = useState<number | null>(null)
  const n = series.length
  const max = Math.max(1, ...series.map((p) => p.runs))
  const slot = W / n
  const bar = Math.max(1, Math.min(slot * 0.7, 28))
  const y = (v: number) => (v / max) * (H - 4)
  return (
    <div className="mx-chart">
      <div className="mx-legend">
        <span><i className="mx-swatch mx-ok" />Succeeded</span>
        <span><i className="mx-swatch mx-failed" />Failed</span>
      </div>
      <div className="mx-plot">
        <div className="mx-area">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
          aria-label={`Runs per interval, ${series.reduce((s, p) => s + p.runs, 0)} in total`}
          onPointerMove={(e) => setHover(bucketAt(e, n))} onPointerLeave={() => setHover(null)}>
          {[0.5, 1].map((f) => <line key={f} className="mx-grid" x1={0} x2={W} y1={H - f * (H - 4)} y2={H - f * (H - 4)} />)}
          {series.map((p, i) => {
            const x = i * slot + (slot - bar) / 2
            const ok = p.runs - p.failed
            const hOk = y(ok)
            const hFail = y(p.failed)
            const gap = ok > 0 && p.failed > 0 ? 2 : 0
            return (
              <g key={p.t} opacity={hover === null || hover === i ? 1 : 0.45}>
                {ok > 0 && <rect className="mx-ok" x={x} y={H - hOk} width={bar} height={hOk} rx={Math.min(2, bar / 2)} />}
                {p.failed > 0 && (
                  <rect className="mx-failed" x={x} y={H - hOk - gap - hFail} width={bar} height={hFail} rx={Math.min(2, bar / 2)} />
                )}
              </g>
            )
          })}
          <line className="mx-baseline" x1={0} x2={W} y1={H} y2={H} />
        </svg>
        {hover !== null && (
          <Tooltip x={hover} n={n}>
            <div className="mx-tip-time">{bucketLabel(series[hover].t, hours)}</div>
            <div><strong>{series[hover].runs}</strong> runs</div>
            <div><i className="mx-swatch mx-failed" /><strong>{series[hover].failed}</strong> failed</div>
          </Tooltip>
        )}
        </div>
        <Axis series={series} hours={hours} max={max} fmt={(v) => String(v)} />
      </div>
    </div>
  )
}

/** p95 run latency per bucket; buckets without runs leave a gap in the line. */
function LatencyChart({ series, hours }: { series: Point[]; hours: number }) {
  const [hover, setHover] = useState<number | null>(null)
  const n = series.length
  const max = Math.max(1, ...series.map((p) => p.p95_ms ?? 0))
  const px = (i: number) => (i + 0.5) * (W / n)
  const py = (v: number) => H - (v / max) * (H - 6)
  let d = ''
  series.forEach((p, i) => {
    if (p.p95_ms == null) return
    const prev = i > 0 ? series[i - 1].p95_ms : null
    d += `${prev == null ? 'M' : 'L'}${px(i).toFixed(1)},${py(p.p95_ms).toFixed(1)} `
  })
  const h = hover !== null ? series[hover] : null
  return (
    <div className="mx-chart">
      <div className="mx-plot">
        <div className="mx-area">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="p95 run latency per interval"
          onPointerMove={(e) => setHover(bucketAt(e, n))} onPointerLeave={() => setHover(null)}>
          {[0.5, 1].map((f) => <line key={f} className="mx-grid" x1={0} x2={W} y1={H - f * (H - 6)} y2={H - f * (H - 6)} />)}
          {hover !== null && <line className="mx-crosshair" x1={px(hover)} x2={px(hover)} y1={0} y2={H} />}
          <path className="mx-line" d={d} />
          <line className="mx-baseline" x1={0} x2={W} y1={H} y2={H} />
        </svg>
        {h?.p95_ms != null && (
          <span className="mx-dot" style={{ left: `${((hover! + 0.5) / n) * 100}%`, top: `${(py(h.p95_ms) / H) * 100}%` }} />
        )}
        {h && (
          <Tooltip x={hover!} n={n}>
            <div className="mx-tip-time">{bucketLabel(h.t, hours)}</div>
            <div>p95 <strong>{h.p95_ms == null ? 'no runs' : ms(h.p95_ms)}</strong></div>
          </Tooltip>
        )}
        </div>
        <Axis series={series} hours={hours} max={max} fmt={(v) => ms(Math.round(v))} />
      </div>
    </div>
  )
}

function SeriesTable({ series, hours }: { series: Point[]; hours: number }) {
  return (
    <details className="mx-table-toggle">
      <summary>View as table</summary>
      <table className="mx-table">
        <thead><tr><th>Interval</th><th>Runs</th><th>Failed</th><th>p95</th><th>Spend</th><th>Tokens</th></tr></thead>
        <tbody>
          {series.filter((p) => p.runs > 0).map((p) => (
            <tr key={p.t}>
              <td>{bucketLabel(p.t, hours)}</td><td>{p.runs}</td><td>{p.failed}</td><td>{ms(p.p95_ms)}</td>
              <td>{usd(p.cost_usd)}</td><td>{p.tokens.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  )
}

/**
 * Monitor → Metrics: how the project's pipelines are doing over a time window — run volume, errors,
 * latency, spend, and where the time goes — from the app database (GET /api/metrics/overview), so it
 * works without Prometheus or Grafana.
 */
export function MetricsPanel({ apps }: { apps: AppOption[] }) {
  const [hours, setHours] = useState(24)
  const [appId, setAppId] = useState('')
  const [nonce, setNonce] = useState(0)   // bumped by Refresh / Retry
  const [result, setResult] = useState<{ key: string; data?: MetricsOverview; error?: string } | null>(null)
  const key = `${hours}|${appId}|${nonce}`

  useEffect(() => {
    let cancelled = false
    const qs = new URLSearchParams({ hours: String(hours), ...(appId ? { app_id: appId } : {}) })
    fetch(`${API_BASE}/api/metrics/overview?${qs}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<MetricsOverview>
      })
      .then((data) => { if (!cancelled) setResult({ key, data }) })
      .catch((e: unknown) => {
        if (!cancelled) setResult({ key, error: `Metrics failed to load (${e instanceof Error ? e.message : 'network error'}).` })
      })
    return () => { cancelled = true }
  }, [hours, appId, key])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  const loading = result?.key !== key
  // Keep showing the last numbers while the next window loads
  const data = result?.data ?? null
  const error = loading ? null : result?.error ?? null

  const t = data?.totals
  const agentFailed = data ? (data.agent_runs.by_status.failed ?? 0) + (data.agent_runs.by_status.rejected ?? 0) : 0
  return (
    <div className="ops-panel mx-panel">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <select className="ops-select" value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Time window">
            {WINDOWS.map((w) => <option key={w.hours} value={w.hours}>{w.label}</option>)}
          </select>
          <select className="ops-select" value={appId} onChange={(e) => setAppId(e.target.value)} aria-label="Pipeline">
            <option value="">All pipelines</option>
            {apps.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <div className="ops-toolbar-right">
          <button type="button" className="ops-refresh-btn" onClick={reload} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && <div className="catalog-error" role="alert"><span>{error}</span><button type="button" onClick={reload}>Retry</button></div>}

      {data && t && (
        <>
          <div className="ops-stats-bar">
            <div className="ops-stat"><span className="ops-stat-value">{t.runs.toLocaleString()}</span><span className="ops-stat-label">Runs</span></div>
            <div className="ops-stat">
              <span className={`ops-stat-value ${t.failed > 0 ? 'ops-stat-value--error' : ''}`}>{pct(t.error_rate)}</span>
              <span className="ops-stat-label">Error rate ({t.failed} failed)</span>
            </div>
            <div className="ops-stat"><span className="ops-stat-value">{ms(t.p50_ms)}</span><span className="ops-stat-label">Median latency</span></div>
            <div className="ops-stat"><span className="ops-stat-value">{ms(t.p95_ms)}</span><span className="ops-stat-label">p95 latency</span></div>
            <div className="ops-stat"><span className="ops-stat-value">{usd(t.cost_usd)}</span><span className="ops-stat-label">Model spend</span></div>
            <div className="ops-stat"><span className="ops-stat-value">{t.tokens.toLocaleString()}</span><span className="ops-stat-label">Tokens</span></div>
            <div className="ops-stat">
              <span className={`ops-stat-value ${data.queue.dead > 0 ? 'ops-stat-value--error' : ''}`}>{data.queue.queued}</span>
              <span className="ops-stat-label">
                Queued jobs{data.queue.queued ? ` · oldest ${wait(data.queue.oldest_wait_s)}` : ''}{data.queue.dead ? ` · ${data.queue.dead} dead` : ''}
              </span>
            </div>
          </div>

          {(t.simulated > 0 || data.truncated) && (
            <p className="mx-note">
              {t.simulated > 0 && <>{t.simulated} of these runs were simulated (mock provider or no API key) and called no model. </>}
              {data.truncated && <>This window has more runs than can be summarised at once; only the newest 50,000 are included.</>}
            </p>
          )}

          {t.runs === 0 ? (
            <div className="ops-empty">No runs in this window. Run a pipeline to see its metrics here.</div>
          ) : (
            <div className="mx-grid-2">
              <section className="cost-card">
                <div className="cost-card-title">Runs</div>
                <RunsChart series={data.series} hours={data.hours} />
                <SeriesTable series={data.series} hours={data.hours} />
              </section>
              <section className="cost-card">
                <div className="cost-card-title">p95 latency over time</div>
                <LatencyChart series={data.series} hours={data.hours} />
              </section>
            </div>
          )}

          <div className="mx-grid-2">
            {data.models.length > 0 && (
              <section className="cost-card">
                <div className="cost-card-title">By model</div>
                <table className="mx-table">
                  <thead><tr><th>Model</th><th>Runs</th><th>Failed</th><th>p95</th><th>Spend</th></tr></thead>
                  <tbody>
                    {data.models.map((m) => (
                      <tr key={`${m.provider}/${m.model}`}>
                        <td className="mono" title={`${m.provider}/${m.model}`}>{m.provider}/{m.model}</td>
                        <td>{m.runs}</td><td>{m.failed}</td><td>{ms(m.p95_ms)}</td><td>{usd(m.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
            {data.tools.length > 0 && (
              <section className="cost-card">
                <div className="cost-card-title">By tool</div>
                <table className="mx-table">
                  <thead><tr><th>Tool</th><th>Calls</th><th>Failed</th><th>p95</th></tr></thead>
                  <tbody>
                    {data.tools.map((r) => (
                      <tr key={r.name}><td>{r.name}</td><td>{r.calls}</td><td>{r.failed}</td><td>{ms(r.p95_ms)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
            {data.phases.length > 0 && (
              <section className="cost-card">
                <div className="cost-card-title">Time outside model and tool calls</div>
                <table className="mx-table">
                  <thead><tr><th>Phase</th><th>Count</th><th>p95</th><th>Total</th></tr></thead>
                  <tbody>
                    {data.phases.map((r) => (
                      <tr key={r.phase}>
                        <td className="mx-cap">{r.phase}</td><td>{r.count}</td><td>{ms(r.p95_ms)}</td><td>{ms(r.total_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
            {data.agent_runs.total > 0 && (
              <section className="cost-card">
                <div className="cost-card-title">Master Agent runs</div>
                <table className="mx-table">
                  <thead><tr><th>Status</th><th>Runs</th></tr></thead>
                  <tbody>
                    {Object.entries(data.agent_runs.by_status).sort((a, b) => b[1] - a[1]).map(([status, count]) => (
                      <tr key={status}><td className="mx-cap">{status}</td><td>{count}</td></tr>
                    ))}
                  </tbody>
                </table>
                {agentFailed > 0 && <p className="mx-note">{agentFailed} failed or rejected.</p>}
              </section>
            )}
          </div>
        </>
      )}
    </div>
  )
}
