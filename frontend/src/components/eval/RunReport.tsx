import { useMemo, useState } from 'react'
import { API_BASE } from '../../types'
import { onDownload } from '../../utils/download'

export interface EvalResultRow {
  id: string
  prompt: string
  actual_output: string
  expected_output: string
  score: number
  pass: number
  latency_ms: number
  cost_usd: number
  error: string | null
  tags?: string[]
}

export interface EvalRunRow {
  id: string
  app_id: string
  app_version?: number
  dataset_id: string
  dataset_name: string
  scorer: string
  total: number
  passed: number
  failed: number
  avg_latency_ms: number
  total_cost_usd: number
  created_at: string
  results?: EvalResultRow[]
}

interface Props {
  run: EvalRunRow
  results: EvalResultRow[]
  pipelineLabel?: string
}

const SCORE_BINS = ['0–19', '20–39', '40–59', '60–79', '80–100']

/** Visual summary of one eval run: KPI tiles, pass/fail meter, pass rate by tag, score histogram. */
export function RunReport({ run, results, pipelineLabel }: Props) {
  const [tip, setTip] = useState<{ x: number; y: number; value: string; label: string } | null>(null)

  const passRate = run.total ? Math.round((run.passed / run.total) * 100) : 0
  const avgScore = results.length ? results.reduce((a, r) => a + r.score, 0) / results.length : 0

  const byTag = useMemo(() => {
    const m = new Map<string, { n: number; p: number }>()
    for (const r of results) {
      for (const t of (r.tags?.length ? r.tags : ['untagged'])) {
        const e = m.get(t) ?? { n: 0, p: 0 }
        e.n += 1
        e.p += r.pass
        m.set(t, e)
      }
    }
    return [...m.entries()].map(([tag, v]) => ({ tag, ...v, rate: v.n ? v.p / v.n : 0 }))
      .sort((a, b) => a.rate - b.rate)   // weakest first: that's where to look
  }, [results])

  const bins = useMemo(() => {
    const out = [0, 0, 0, 0, 0]
    for (const r of results) out[Math.min(4, Math.floor(r.score * 5))] += 1
    return out
  }, [results])
  const maxBin = Math.max(1, ...bins)

  const showTip = (e: React.PointerEvent | React.FocusEvent, value: string, label: string) => {
    const host = (e.currentTarget as HTMLElement).closest('.viz-root')!.getBoundingClientRect()
    const box = (e.currentTarget as Element).getBoundingClientRect()
    setTip({ x: box.left + box.width / 2 - host.left, y: box.top - host.top, value, label })
  }

  return (
    <div className="viz-root run-report" onPointerLeave={() => setTip(null)}>
      <div className="viz-head">
        <div>
          <div className="viz-title">{run.dataset_name}</div>
          <div className="viz-sub">
            {pipelineLabel ? `${pipelineLabel} · ` : ''}{run.scorer} scorer · {new Date(run.created_at).toLocaleString()}
          </div>
        </div>
        <div className="viz-export">
          <button type="button" className="eval-action-btn" onClick={onDownload(`${API_BASE}/api/eval/runs/${run.id}/export?format=xlsx`, 'eval-run.xlsx')}>⬇ Excel</button>
          <button type="button" className="eval-action-btn" onClick={onDownload(`${API_BASE}/api/eval/runs/${run.id}/export?format=csv`, 'eval-run.csv')}>⬇ CSV</button>
        </div>
      </div>

      {/* KPI row */}
      <div className="viz-kpis">
        <div className="viz-tile viz-tile--hero">
          <span className="viz-tile-label">Pass rate</span>
          <span className="viz-tile-value">{passRate}%</span>
        </div>
        <div className="viz-tile">
          <span className="viz-tile-label">Cases</span>
          <span className="viz-tile-value">{run.passed}<span className="viz-tile-of">/{run.total}</span></span>
        </div>
        <div className="viz-tile">
          <span className="viz-tile-label">Avg score</span>
          <span className="viz-tile-value">{Math.round(avgScore * 100)}</span>
        </div>
        <div className="viz-tile">
          <span className="viz-tile-label">Avg latency</span>
          <span className="viz-tile-value">{run.avg_latency_ms >= 1000 ? `${(run.avg_latency_ms / 1000).toFixed(1)}s` : `${Math.round(run.avg_latency_ms)}ms`}</span>
        </div>
        <div className="viz-tile">
          <span className="viz-tile-label">Cost</span>
          <span className="viz-tile-value">${run.total_cost_usd.toFixed(run.total_cost_usd < 1 ? 4 : 2)}</span>
        </div>
      </div>

      {/* Pass / fail meter — status colors always paired with icon + label */}
      {run.total > 0 && (
        <div className="viz-meter-wrap">
          <div className="viz-meter" role="img" aria-label={`${run.passed} passed, ${run.failed} failed`}>
            {run.passed > 0 && <span className="viz-meter-seg viz-meter-seg--good" style={{ flexGrow: run.passed }} />}
            {run.failed > 0 && <span className="viz-meter-seg viz-meter-seg--bad" style={{ flexGrow: run.failed }} />}
          </div>
          <div className="viz-meter-legend">
            <span><span className="viz-status viz-status--good">✓</span> {run.passed} passed</span>
            <span><span className="viz-status viz-status--bad">✗</span> {run.failed} failed</span>
          </div>
        </div>
      )}

      <div className="viz-grid">
        {/* Pass rate by tag — horizontal bars, one hue, direct-labelled */}
        <figure className="viz-card">
          <figcaption className="viz-card-title">Pass rate by tag</figcaption>
          {byTag.length === 0 && <div className="viz-empty">No results yet</div>}
          <div className="viz-hbars">
            {byTag.map((t) => (
              <div key={t.tag} className="viz-hbar-row">
                <span className="viz-hbar-label">{t.tag.replace(/_/g, ' ')}</span>
                <span
                  className="viz-hbar-track"
                  tabIndex={0}
                  onPointerMove={(e) => showTip(e, `${Math.round(t.rate * 100)}%`, `${t.tag.replace(/_/g, ' ')} · ${t.p}/${t.n} passed`)}
                  onFocus={(e) => showTip(e, `${Math.round(t.rate * 100)}%`, `${t.tag.replace(/_/g, ' ')} · ${t.p}/${t.n} passed`)}
                  onBlur={() => setTip(null)}
                >
                  <span className="viz-hbar" style={{ width: `${Math.max(t.rate * 100, t.rate > 0 ? 2 : 0)}%` }} />
                </span>
                <span className="viz-hbar-value">{Math.round(t.rate * 100)}% <span className="viz-muted">({t.p}/{t.n})</span></span>
              </div>
            ))}
          </div>
        </figure>

        {/* Score distribution — columns, one hue */}
        <figure className="viz-card">
          <figcaption className="viz-card-title">Score distribution</figcaption>
          <div className="viz-cols" role="img" aria-label={SCORE_BINS.map((b, i) => `${b}: ${bins[i]}`).join(', ')}>
            {bins.map((n, i) => (
              <div key={SCORE_BINS[i]} className="viz-col-slot">
                <span className="viz-col-value">{n > 0 ? n : ''}</span>
                <span
                  className="viz-col-hit"
                  tabIndex={0}
                  onPointerMove={(e) => showTip(e, `${n} case${n === 1 ? '' : 's'}`, `score ${SCORE_BINS[i]}`)}
                  onFocus={(e) => showTip(e, `${n} case${n === 1 ? '' : 's'}`, `score ${SCORE_BINS[i]}`)}
                  onBlur={() => setTip(null)}
                >
                  <span className="viz-col" style={{ height: `${(n / maxBin) * 100}%` }} />
                </span>
                <span className="viz-col-label">{SCORE_BINS[i]}</span>
              </div>
            ))}
          </div>
        </figure>
      </div>

      {tip && (
        <div className="viz-tooltip" style={{ left: tip.x, top: tip.y }}>
          <strong>{tip.value}</strong>
          <span>{tip.label}</span>
        </div>
      )}
    </div>
  )
}
