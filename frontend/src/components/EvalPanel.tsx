import { useState, useCallback, useEffect } from 'react'
import { API_BASE } from '../types'
import type { AppRecord, FlowNode, FlowEdge } from '../types'
import { AiCaseGenerator } from './eval/AiCaseGenerator'
import { DatasetDetail } from './eval/DatasetDetail'
import type { EvalDatasetRow } from './eval/DatasetDetail'
import { RunReport } from './eval/RunReport'
import type { EvalResultRow as EvalResult, EvalRunRow as EvalRun } from './eval/RunReport'
import { PassRateTrend } from './eval/PassRateTrend'
import { ModelOptimizer } from './eval/ModelOptimizer'
import { ReviewQueue } from './eval/ReviewQueue'
import { FeedbackPanel } from './eval/FeedbackPanel'
import { useCredentials } from '../context/CredentialsContext'
import { onDownload } from '../utils/download'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Props {
  nodes?: FlowNode[]
  edges?: FlowEdge[]
  currentAppId?: string
}

type Tab = 'datasets' | 'run' | 'history' | 'optimize' | 'review' | 'feedback'
type Scorer = 'contains' | 'exact' | 'llm_judge'

// ── Component ─────────────────────────────────────────────────────────────────

export function EvalPanel({ nodes = [], edges = [], currentAppId }: Props) {
  const [tab, setTab] = useState<Tab>('datasets')
  const { resolveApiKey } = useCredentials()

  // datasets tab state
  const [datasets, setDatasets] = useState<EvalDatasetRow[]>([])
  const [apps, setApps] = useState<AppRecord[]>([])
  const [datasetsLoaded, setDatasetsLoaded] = useState(false)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  // new dataset form
  const [newDsName, setNewDsName] = useState('')
  const [newDsDesc, setNewDsDesc] = useState('')
  const [showNewDs, setShowNewDs] = useState(false)
  const [savedMsg, setSavedMsg] = useState<string | null>(null)

  // run tab state
  const [runDatasetId, setRunDatasetId] = useState<string | null>(null)
  const [scorer, setScorer] = useState<Scorer>('contains')
  const [running, setRunning] = useState(false)
  const [runProgress, setRunProgress] = useState<string | null>(null)
  const [lastRun, setLastRun] = useState<EvalRun | null>(null)
  const [expandedResult, setExpandedResult] = useState<string | null>(null)

  // history tab state
  const [history, setHistory] = useState<EvalRun[]>([])
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [expandedRun, setExpandedRun] = useState<string | null>(null)
  const [expandedRunResults, setExpandedRunResults] = useState<Record<string, EvalResult[]>>({})
  const [historyDatasetId, setHistoryDatasetId] = useState<string>('')

  // ── Data fetchers ──────────────────────────────────────────────────────────

  const fetchDatasets = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/eval/datasets`)
      const d = await r.json()
      setDatasets(d)
      setDatasetsLoaded(true)
    } catch { /* backend unreachable */ }
  }, [])

  const fetchHistory = useCallback(async () => {
    try {
      const url = currentAppId
        ? `${API_BASE}/api/eval/runs?app_id=${currentAppId}`
        : `${API_BASE}/api/eval/runs`
      const r = await fetch(url)
      const d = await r.json()
      setHistory(d)
      setHistoryLoaded(true)
    } catch { /* ignore */ }
  }, [currentAppId])

  useEffect(() => { fetchDatasets() }, [fetchDatasets])
  useEffect(() => {
    fetch(`${API_BASE}/api/apps`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setApps)
      .catch(() => setApps([]))
  }, [])
  const pipelineLabel = (appId: string | null | undefined, version?: number) => {
    if (!appId) return null
    const a = apps.find((x) => x.id === appId)
    return `${a?.name ?? 'deleted pipeline'} ${version ? `v${version}` : 'draft'}`
  }
  const appLabel = (ds: EvalDatasetRow) => pipelineLabel(ds.app_id, ds.app_version)

  // ── Dataset actions ────────────────────────────────────────────────────────

  const createDataset = async () => {
    if (!newDsName.trim()) return
    const r = await fetch(`${API_BASE}/api/eval/datasets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newDsName.trim(), description: newDsDesc.trim(), app_id: currentAppId }),
    })
    if (r.ok) {
      setNewDsName(''); setNewDsDesc(''); setShowNewDs(false)
      await fetchDatasets()
    }
  }

  const deleteDataset = async (dsId: string) => {
    if (!window.confirm('Delete this dataset and all its test cases?')) return
    await fetch(`${API_BASE}/api/eval/datasets/${dsId}`, { method: 'DELETE' })
    if (selectedDatasetId === dsId) setSelectedDatasetId(null)
    await fetchDatasets()
  }

  const selectDataset = (dsId: string) => {
    setSelectedDatasetId(selectedDatasetId === dsId ? null : dsId)
  }

  // ── Eval run ───────────────────────────────────────────────────────────────

  const runDataset = datasets.find((d) => d.id === (runDatasetId || selectedDatasetId))
  // Embedded in Build with a live canvas: legacy single-LLM run; otherwise run the dataset's linked pipeline
  const useCanvas = nodes.length > 0 && !!currentAppId

  const runEval = async () => {
    const ds = runDataset
    if (!ds || (!useCanvas && !ds.app_id)) return
    setRunning(true)
    setLastRun(null)
    setRunProgress(`Running ${ds.case_count} case${ds.case_count === 1 ? '' : 's'} against ${
      useCanvas ? 'the canvas' : pipelineLabel(ds.app_id, ds.app_version)}…`)
    try {
      const body = useCanvas
        ? { app_id: currentAppId, dataset_id: ds.id, scorer, flow_data: { nodes: nodes as any[], edges: edges as any[] } }
        : {
            app_id: ds.app_id, app_version: ds.app_version ?? 0, dataset_id: ds.id, scorer,
            provider_keys: {
              openai: resolveApiKey('openai'), anthropic: resolveApiKey('anthropic'),
              groq: resolveApiKey('groq'), gemini: resolveApiKey('gemini'), mistral: resolveApiKey('mistral'),
            },
          }
      const r = await fetch(`${API_BASE}/api/eval/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) { const e = await r.json().catch(() => ({})); setRunProgress(`Error: ${e.detail ?? r.statusText}`); return }
      const run: EvalRun = await r.json()
      setLastRun(run)
      setRunProgress(null)
      setTab('run')
      setHistoryLoaded(false) // force re-fetch history
    } finally { setRunning(false) }
  }

  const loadRunResults = async (runId: string) => {
    if (expandedRunResults[runId]) {
      setExpandedRun(expandedRun === runId ? null : runId)
      return
    }
    try {
      const r = await fetch(`${API_BASE}/api/eval/runs/${runId}/results`)
      const d = await r.json()
      setExpandedRunResults((prev) => ({ ...prev, [runId]: d }))
      setExpandedRun(runId)
    } catch { /* ignore */ }
  }

  const deleteRun = async (runId: string) => {
    await fetch(`${API_BASE}/api/eval/runs/${runId}`, { method: 'DELETE' })
    setHistory((prev) => prev.filter((r) => r.id !== runId))
  }

  // ── Render helpers ─────────────────────────────────────────────────────────

  const passRate = (run: EvalRun) =>
    run.total > 0 ? Math.round((run.passed / run.total) * 100) : 0

  const scoreColor = (score: number) =>
    score >= 0.8 ? '#16a34a' : score >= 0.5 ? '#d97706' : '#dc2626'

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="eval-panel-body">

          {/* Tab bar */}
          <div className="eval-tabs">
            {(['datasets', 'run', 'history', 'optimize', 'review', 'feedback'] as Tab[]).map((t) => (
              <button
                key={t}
                type="button"
                className={`eval-tab${tab === t ? ' eval-tab--active' : ''}`}
                onClick={() => {
                  setTab(t)
                  if (t === 'history' && !historyLoaded) fetchHistory()
                  if ((t === 'datasets' || t === 'optimize' || t === 'feedback') && !datasetsLoaded) fetchDatasets()
                }}
              >
                {t === 'datasets' ? '📋 Datasets' : t === 'run' ? '▶ Run' : t === 'history' ? '📊 History' : t === 'optimize' ? '⚡ Optimize' : t === 'review' ? '🧾 Review' : '👍 Feedback'}
              </button>
            ))}
          </div>

          {/* ── DATASETS TAB ── */}
          {tab === 'datasets' && (
            <div className="eval-tab-body">
              <div className="eval-toolbar">
                <button type="button" className="eval-action-btn" onClick={fetchDatasets}>↻ Refresh</button>
                <button type="button" className="eval-action-btn eval-action-btn--primary" onClick={() => setShowNewDs(!showNewDs)}>
                  + New Dataset
                </button>
              </div>

              {datasetsLoaded && (
                <AiCaseGenerator
                  apps={apps}
                  datasets={datasets}
                  defaultOpen={datasets.length === 0}
                  onSaved={async (dsId, message) => {
                    await fetchDatasets()
                    setSelectedDatasetId(dsId)
                    setSavedMsg(message)
                    setTimeout(() => setSavedMsg(null), 4000)
                  }}
                />
              )}
              {savedMsg && <div className="eval-generate-msg">{savedMsg}</div>}

              {showNewDs && (
                <div className="eval-form-card">
                  <input
                    type="text" placeholder="Dataset name (e.g. SQL queries)"
                    className="eval-input" value={newDsName}
                    onChange={(e) => setNewDsName(e.target.value)}
                  />
                  <input
                    type="text" placeholder="Description (optional)"
                    className="eval-input" value={newDsDesc}
                    onChange={(e) => setNewDsDesc(e.target.value)}
                  />
                  <div className="eval-form-actions">
                    <button type="button" className="eval-save-btn" onClick={createDataset}>Create</button>
                    <button type="button" className="eval-cancel-btn" onClick={() => setShowNewDs(false)}>Cancel</button>
                  </div>
                </div>
              )}

              {datasets.length === 0 && datasetsLoaded && (
                <div className="eval-empty">No datasets yet. Generate cases with AI above, or create one manually.</div>
              )}

              <div className="eval-dataset-list">
                {datasets.map((ds) => (
                  <div key={ds.id} className={`eval-dataset-row${selectedDatasetId === ds.id ? ' eval-dataset-row--active' : ''}`}>
                    <div className="eval-dataset-header" onClick={() => selectDataset(ds.id)}>
                      <span className="ds-caret">{selectedDatasetId === ds.id ? '▾' : '▸'}</span>
                      <span className="eval-dataset-name">{ds.name}</span>
                      {appLabel(ds) && <span className="ds-pipeline-badge">{appLabel(ds)}</span>}
                      <span className="eval-dataset-count">
                        {ds.case_count} case{ds.case_count === 1 ? '' : 's'}{ds.ai_count ? ` · ${ds.ai_count} AI` : ''}
                      </span>
                      <button type="button" className="eval-del-btn" title="Delete dataset" onClick={(e) => { e.stopPropagation(); deleteDataset(ds.id) }}>✕</button>
                    </div>
                    {ds.description && <div className="eval-dataset-desc">{ds.description}</div>}

                    {selectedDatasetId === ds.id && (
                      <DatasetDetail
                        dataset={ds}
                        datasets={datasets}
                        apps={apps}
                        onChanged={fetchDatasets}
                        onRun={() => { setRunDatasetId(ds.id); setTab('run') }}
                      />
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── RUN TAB ── */}
          {tab === 'run' && (
            <div className="eval-tab-body">
              <div className="eval-run-config">
                <div className="eval-field">
                  <label className="eval-label">Dataset</label>
                  <select
                    className="eval-select"
                    value={runDatasetId || ''}
                    onChange={(e) => setRunDatasetId(e.target.value || null)}
                  >
                    <option value="">— select dataset —</option>
                    {datasets.map((ds) => (
                      <option key={ds.id} value={ds.id}>{ds.name} ({ds.case_count} cases)</option>
                    ))}
                  </select>
                </div>
                <div className="eval-field">
                  <label className="eval-label">Scorer</label>
                  <select className="eval-select" value={scorer} onChange={(e) => setScorer(e.target.value as Scorer)}>
                    <option value="contains">Contains — expected substring in output</option>
                    <option value="exact">Exact — full string match</option>
                    <option value="llm_judge">LLM Judge — AI scores 0–1 (costs tokens)</option>
                  </select>
                </div>

                {runDataset && !useCanvas && (
                  runDataset.app_id
                    ? <div className="eval-label">Runs every case through <strong>{pipelineLabel(runDataset.app_id, runDataset.app_version)}</strong> — sub-pipelines, tools and RAG included.</div>
                    : <div className="eval-warn">⚠ This dataset isn't linked to a pipeline. Link one in Datasets → ⚙ Settings.</div>
                )}

                <button
                  type="button"
                  className="eval-run-btn"
                  disabled={running || !runDataset || !runDataset.case_count || (!useCanvas && !runDataset.app_id)}
                  onClick={runEval}
                >
                  {running ? '⏳ Running…' : '▶ Run Eval'}
                </button>
                {runProgress && <div className="eval-progress">{runProgress}</div>}
              </div>

              {lastRun && (
                <div className="eval-run-results">
                  <RunReport
                    run={lastRun}
                    results={lastRun.results ?? []}
                    pipelineLabel={pipelineLabel(lastRun.app_id, lastRun.app_version) ?? undefined}
                  />
                  <ResultList results={lastRun.results ?? []} expanded={expandedResult} onToggle={setExpandedResult} scoreColor={scoreColor} />
                </div>
              )}
            </div>
          )}

          {/* ── HISTORY TAB ── */}
          {tab === 'history' && (() => {
            const runDatasets = [...new Map(history.map((r) => [r.dataset_id, r.dataset_name])).entries()]
            const shown = historyDatasetId ? history.filter((r) => r.dataset_id === historyDatasetId) : history
            return (
            <div className="eval-tab-body">
              <div className="eval-toolbar">
                <button type="button" className="eval-action-btn" onClick={fetchHistory}>↻ Refresh</button>
                <select className="eval-select ds-history-filter" value={historyDatasetId} onChange={(e) => setHistoryDatasetId(e.target.value)}>
                  <option value="">All datasets ({history.length} runs)</option>
                  {runDatasets.map(([id, name]) => (
                    <option key={id} value={id}>{name} ({history.filter((r) => r.dataset_id === id).length} runs)</option>
                  ))}
                </select>
              </div>
              {history.length === 0 && historyLoaded && (
                <div className="eval-empty">No eval runs yet.</div>
              )}

              {historyDatasetId ? (
                <figure className="viz-root viz-card viz-card--wide">
                  <figcaption className="viz-card-title">Pass rate over time</figcaption>
                  <PassRateTrend runs={shown} />
                </figure>
              ) : history.length > 1 && (
                <div className="eval-label">Pick a dataset above to see its pass-rate trend.</div>
              )}

              <div className="eval-history-list">
                {shown.map((run) => (
                  <div key={run.id} className="eval-history-row">
                    <div className="eval-history-header" onClick={() => loadRunResults(run.id)}>
                      <span className="eval-pass-rate" style={{ color: scoreColor(run.passed / (run.total || 1)) }}>
                        {passRate(run)}%
                      </span>
                      <div className="eval-history-meta">
                        <span className="eval-history-name">{run.dataset_name}</span>
                        <span className="eval-history-detail">
                          {pipelineLabel(run.app_id, run.app_version) ?? run.app_id} · {run.passed}/{run.total} passed · {run.scorer} · {run.avg_latency_ms}ms · ${run.total_cost_usd.toFixed(4)}
                        </span>
                        <span className="eval-history-time">{new Date(run.created_at).toLocaleString()}</span>
                      </div>
                      <button type="button" className="eval-action-btn" onClick={onDownload(`${API_BASE}/api/eval/runs/${run.id}/export?format=xlsx`, 'eval-run.xlsx')} title="Export results to Excel">⬇</button>
                      <button type="button" className="eval-del-btn" onClick={(e) => { e.stopPropagation(); deleteRun(run.id) }}>✕</button>
                    </div>

                    {expandedRun === run.id && expandedRunResults[run.id] && (
                      <div className="eval-history-detail-body">
                        <RunReport run={run} results={expandedRunResults[run.id]} pipelineLabel={pipelineLabel(run.app_id, run.app_version) ?? undefined} />
                        <ResultList results={expandedRunResults[run.id]} expanded={expandedResult} onToggle={setExpandedResult} scoreColor={scoreColor} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
            )
          })()}

          {/* ── OPTIMIZE TAB ── */}
          {tab === 'optimize' && <ModelOptimizer datasets={datasets} pipelineLabel={pipelineLabel} />}
          {tab === 'review' && <ReviewQueue onExported={fetchDatasets} />}
          {tab === 'feedback' && <FeedbackPanel datasets={datasets} onExported={fetchDatasets} />}

    </div>
  )
}


/** Per-case results — the table view behind the charts. */
function ResultList({ results, expanded, onToggle, scoreColor }: {
  results: EvalResult[]
  expanded: string | null
  onToggle: (id: string | null) => void
  scoreColor: (score: number) => string
}) {
  const [failedOnly, setFailedOnly] = useState(false)
  const shown = failedOnly ? results.filter((r) => !r.pass) : results
  return (
    <div className="eval-result-list">
      <label className="ds-check-all eval-label">
        <input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} />
        Failed only ({results.filter((r) => !r.pass).length})
      </label>
      {shown.map((res) => (
        <div key={res.id} className={`eval-result-row${res.pass ? ' eval-result-row--pass' : ' eval-result-row--fail'}`}>
          <div className="eval-result-header" onClick={() => onToggle(expanded === res.id ? null : res.id)}>
            <span className="eval-result-status">{res.pass ? '✓' : '✗'}</span>
            <span className="eval-result-idx">#{results.indexOf(res) + 1}</span>
            <span className="eval-result-prompt">{res.prompt.slice(0, 70)}{res.prompt.length > 70 ? '…' : ''}</span>
            {(res.tags ?? []).slice(0, 2).map((t) => <span key={t} className={`ai-gen-tag ai-gen-tag--${t}`}>{t.replace(/_/g, ' ')}</span>)}
            <span className="eval-result-score" style={{ color: scoreColor(res.score) }}>
              {(res.score * 100).toFixed(0)}%
            </span>
            <span className="eval-result-lat">{res.latency_ms}ms</span>
          </div>
          {expanded === res.id && (
            <div className="eval-result-detail">
              <div className="eval-detail-label">Prompt</div>
              <div className="eval-detail-value">{res.prompt}</div>
              {res.expected_output && <>
                <div className="eval-detail-label">Expected</div>
                <div className="eval-detail-value eval-detail-expected">{res.expected_output}</div>
              </>}
              <div className="eval-detail-label">Actual</div>
              <div className="eval-detail-value eval-detail-actual">{res.actual_output || '(empty)'}</div>
              {res.error && <div className="eval-detail-error">Error: {res.error}</div>}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
