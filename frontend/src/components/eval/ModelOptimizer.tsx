/**
 * Evaluate → Optimize: find the cheapest (or fastest) model for every LLM node of a pipeline that
 * keeps its eval pass rate. The search runs as a background job (services/model_routing.py);
 * this tab starts it, polls its progress, and applies the winner to the pipeline's draft.
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { API_BASE } from '../../types'
import type { ProviderOption } from '../../types'
import type { EvalDatasetRow } from './DatasetDetail'
import { useCredentials } from '../../context/CredentialsContext'

type Choice = { provider: string; model: string }
type Assignment = Record<string, Choice>

export interface OptimizeSlot {
  key: string
  app_id: string
  node_id: string
  node_type: string
  label: string
  source: string
  provider: string
  model: string
}

export interface OptimizeConfig {
  assignment: Assignment
  phase: 'baseline' | 'screen' | 'single' | 'combined'
  cases: number
  pass_rate: number
  mean_score: number
  cost_per_case_usd: number
  avg_latency_ms: number
  errors: number
  first_error?: string | null
  meets_target: boolean | null
}

export interface OptimizeCase {
  case_id: string
  prompt: string
  expected_output: string
  output: string
  score: number
  passed: boolean
  cost_usd: number
  latency_ms: number
  error: string | null
}

export interface OptimizeStudy {
  id: string
  app_id: string
  app_version: number
  dataset_id: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  /** What the study was started with (provider keys removed); Re-run sends it again */
  request: {
    scorer?: string; objective?: 'cost' | 'latency'; tolerance?: number; screen_cases?: number; max_configs?: number
    candidates?: Choice[]; slot_candidates?: Record<string, Choice[]>; timeout_ms?: number
    slot_keys?: string[]; parallel?: number
  }
  result: {
    objective: 'cost' | 'latency'
    tolerance: number
    done: boolean
    configs_run: number
    max_configs: number
    truncated: boolean
    planned_configs?: number
    current?: {
      assignment: Assignment; phase: OptimizeConfig['phase']; index?: number; cases_done: number; cases_total: number
      passed?: number; cost_usd?: number; latency_ms?: number
    } | null
    slots: OptimizeSlot[]
    baseline: OptimizeConfig | null
    best: OptimizeConfig | null
    tried: OptimizeConfig[]
    warnings?: string[]
  } | null
  error: string | null
  created_at: string
  updated_at?: string
}

interface ApplyResult {
  applied: { key: string; label: string; provider: string; model: string }[]
  skipped: { key: string; label: string; reason: string }[]
}

interface Props {
  datasets: EvalDatasetRow[]
  pipelineLabel: (appId: string | null | undefined, version?: number) => string | null
  /** Polling interval while a study runs; tests shorten it. */
  pollMs?: number
}

const POLL_MS = 2000
const LAST_DATASET = 'pipesets.optimize.dataset'   // per-viewer convenience: reopen where you left off
const WIDE = '(min-width: 1100px)'   // keep in step with .opt-layout in styles/eval.css
// Run without an API key, so they're always offered
const KEYLESS = new Set(['ollama', 'llamacpp', 'jan', 'huggingface'])
const PHASE_LABEL: Record<OptimizeConfig['phase'], string> = {
  baseline: 'Saved models', screen: 'Screen', single: 'One swap', combined: 'Combined',
}

// Keep two significant digits on sub-cent costs, so cheap models don't all show $0.00000
const usd = (v: number) => `$${v.toFixed(v >= 0.01 ? 4 : v >= 0.001 ? 5 : 6)}`
const pct = (v: number) => `${Math.round(v * 100)}%`
/** Studies stopped before the cancel endpoint existed were saved as failed with "Cancelled". */
const normalized = (s: OptimizeStudy): OptimizeStudy =>
  (s.status === 'failed' && /^cancell?ed/i.test(s.error ?? '') ? { ...s, status: 'cancelled' } : s)

const STATUS_LABEL: Record<OptimizeStudy['status'], string> = {
  queued: 'Queued', running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Cancelled',
}

// The backend stores UTC without an offset
const utc = (iso: string) => new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
const when = (iso: string) => utc(iso).toLocaleString()
const duration = (ms: number) => {
  const s = Math.max(0, Math.round(ms / 1000))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}
const same = (a: Assignment, b: Assignment) => JSON.stringify(a) === JSON.stringify(b)

async function detail(r: Response): Promise<string> {
  const body = await r.json().catch(() => ({}))
  return typeof body.detail === 'string' ? body.detail : r.statusText
}

export function ModelOptimizer({ datasets, pipelineLabel, pollMs = POLL_MS }: Props) {
  const { resolveApiKey } = useCredentials()
  const linked = datasets.filter((d) => d.app_id)

  const [datasetId, setDatasetId] = useState(() => {
    try { return localStorage.getItem(LAST_DATASET) ?? '' } catch { return '' }
  })
  const [scorer, setScorer] = useState('contains')
  const [objective, setObjective] = useState<'cost' | 'latency'>('cost')
  const [tolerancePct, setTolerancePct] = useState(0)
  const [screenCases, setScreenCases] = useState(0)
  const [maxConfigs, setMaxConfigs] = useState(40)
  const [parallel, setParallel] = useState(4)
  // nodes left out of the search (they keep their saved models); every node is in by default
  const [skipped, setSkipped] = useState<Set<string>>(new Set())
  const [providers, setProviders] = useState<ProviderOption[]>([])
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [slots, setSlots] = useState<OptimizeSlot[]>([])
  const [slotError, setSlotError] = useState<string | null>(null)
  const [study, setStudy] = useState<OptimizeStudy | null>(null)
  const [past, setPast] = useState<OptimizeStudy[]>([])
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [applied, setApplied] = useState<ApplyResult | null>(null)
  const [allProviders, setAllProviders] = useState(false)
  // the config row whose cases are shown, per study
  const [openConfig, setOpenConfig] = useState<{ study: string; index: number } | null>(null)
  const studyRef = useRef<HTMLDivElement>(null)

  const dataset = linked.find((d) => d.id === datasetId)

  useEffect(() => {
    fetch(`${API_BASE}/api/models`)
      .then((r) => (r.ok ? r.json() : { providers: [] }))
      .then((d) => setProviders((d.providers ?? []).filter((p: ProviderOption) => p.id !== 'mock' && p.models.length)))
      .catch(() => setProviders([]))
  }, [])

  // This pipeline's optimizations, or the project's when no dataset is picked
  const loadPast = useCallback(async (appId?: string | null) => {
    try {
      const q = appId ? `?app_id=${encodeURIComponent(appId)}` : ''
      const r = await fetch(`${API_BASE}/api/eval/optimizations${q}`)
      if (!r.ok) return
      const list: OptimizeStudy[] = await r.json()
      setPast(list)
      if (appId) setStudy((open) => open ?? list[0] ?? null)   // open the pipeline's latest when nothing is open
    } catch { /* backend unreachable */ }
  }, [])

  useEffect(() => { loadPast(dataset?.app_id) }, [dataset?.app_id, loadPast])

  // The nodes the dataset's pipeline lets the search change
  useEffect(() => {
    if (!dataset?.app_id) return
    const appId = dataset.app_id
    fetch(`${API_BASE}/api/eval/optimize-models/slots`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id: appId, app_version: dataset.app_version ?? 0 }),
    })
      .then(async (r) => {
        if (!r.ok) { setSlotError(await detail(r)); return }
        const d = await r.json()
        setSlots(d.slots ?? [])
        if (d.errors?.length) setSlotError(d.errors.join('; '))
      })
      .catch(() => setSlotError('Backend unreachable'))
  }, [dataset?.app_id, dataset?.app_version])

  // Bring the results into view when a study starts or is opened
  useEffect(() => {
    if (window.matchMedia?.(WIDE).matches) return   // side by side: already in view
    studyRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }, [study?.id])

  // Poll the running study
  const running = study?.status === 'queued' || study?.status === 'running'
  useEffect(() => {
    if (!study || !running) return
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${API_BASE}/api/eval/optimizations/${study.id}`)
        if (r.ok) {
          const next: OptimizeStudy = await r.json()
          setStudy(next)
          setPast((list) => list.map((p) => (p.id === next.id ? next : p)))
          if (next.status === 'done' || next.status === 'failed') loadPast(dataset?.app_id)
        }
      } catch { /* try again next tick */ }
    }, pollMs)
    return () => clearTimeout(t)
  }, [study, running, pollMs, loadPast, dataset?.app_id])

  const candidates: Choice[] = useMemo(
    () => [...picked].map((k) => { const i = k.indexOf('/'); return { provider: k.slice(0, i), model: k.slice(i + 1) } }),
    [picked],
  )
  // Upper bound: baseline + every single swap (+ its screen) + one combination per slot
  const chosen = slots.filter((s) => !skipped.has(s.key))
  // Screens only run when they use fewer cases than the dataset (see model_routing.search)
  const screening = screenCases > 0 && screenCases < (dataset?.case_count ?? 0)
  const estConfigs = Math.min(maxConfigs,
    1 + chosen.length * candidates.length * (screening ? 2 : 1) + Math.max(0, chosen.length - 1))
  const estimate = { configs: estConfigs, runs: estConfigs * (dataset?.case_count ?? 0) }

  // Providers you have a key for (and any with a picked model) first; the rest behind a toggle
  const usable = (p: ProviderOption) => KEYLESS.has(p.id) || !!resolveApiKey(p.id)
    || p.models.some((m) => picked.has(`${p.id}/${m}`))
  const keyed = providers.filter(usable)
  const shownProviders = allProviders || !keyed.length ? providers : keyed

  const toggle = (key: string) => setPicked((prev) => {
    const next = new Set(prev)
    if (next.has(key)) next.delete(key); else next.add(key)
    return next
  })

  const selectDataset = (id: string, keepStudy = false) => {
    if (id === datasetId) return
    setSlots([]); setSlotError(null); setSkipped(new Set())
    setDatasetId(id)
    if (!keepStudy) setStudy(null)
    setApplied(null)
    try { localStorage.setItem(LAST_DATASET, id) } catch { /* storage blocked */ }
  }

  const submit = async (body: Record<string, unknown> & { candidates: Choice[] }, slotProviders: string[]) => {
    setStarting(true); setError(null); setApplied(null)
    const used = new Set([...body.candidates.map((c) => c.provider), ...slotProviders.map((p) => p.toLowerCase())])
    const provider_keys = Object.fromEntries([...used].map((p) => [p, resolveApiKey(p)]).filter(([, k]) => k))
    try {
      const r = await fetch(`${API_BASE}/api/eval/optimize-models`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...body, provider_keys }),
      })
      if (!r.ok) { setError(await detail(r)); return }
      const created: OptimizeStudy = await r.json()
      setStudy(created)
      setPast((list) => [created, ...list.filter((p) => p.id !== created.id)])
    } catch {
      setError('Backend unreachable')
    } finally { setStarting(false) }
  }

  const start = () => {
    if (!dataset?.app_id) return
    submit({
      app_id: dataset.app_id, app_version: dataset.app_version ?? 0, dataset_id: dataset.id, scorer, objective,
      tolerance: tolerancePct / 100, screen_cases: screenCases, max_configs: maxConfigs, candidates, parallel,
      slot_keys: chosen.length < slots.length ? chosen.map((s) => s.key) : [],
    }, slots.map((s) => s.provider))
  }

  /** Put an old study's settings back in the form (and open it), to change the models and start again. */
  const loadSettings = (p: OptimizeStudy) => {
    const q = p.request
    selectDataset(p.dataset_id, true)
    setStudy(p)
    setScorer(q.scorer ?? 'contains')
    setObjective(q.objective ?? 'cost')
    setTolerancePct(Math.round((q.tolerance ?? 0) * 100))
    setScreenCases(q.screen_cases ?? 0)
    setMaxConfigs(q.max_configs ?? 40)
    setParallel(q.parallel ?? 1)
    setSkipped(new Set(q.slot_keys?.length ? (p.result?.slots ?? slots).map((s) => s.key)
      .filter((k) => !q.slot_keys!.includes(k)) : []))
    setPicked(new Set((q.candidates ?? []).map((c) => `${c.provider}/${c.model}`)))
  }

  /** Start an old study again, exactly as it was set up. */
  const rerun = (p: OptimizeStudy) => {
    loadSettings(p)
    submit({ ...p.request, candidates: p.request.candidates ?? [], app_id: p.app_id, app_version: p.app_version,
      dataset_id: p.dataset_id }, (p.result?.slots ?? []).map((s) => s.provider))
  }

  const openStudy = (p: OptimizeStudy) => {
    if (linked.some((d) => d.id === p.dataset_id)) selectDataset(p.dataset_id, true)
    setStudy(p)
    setApplied(null)
  }
  const canRerun = (p: OptimizeStudy) => linked.some((d) => d.id === p.dataset_id) && !!p.request.candidates?.length
  const datasetName = (id: string) => datasets.find((d) => d.id === id)?.name ?? 'deleted dataset'

  const cancel = async () => {
    if (!study || !window.confirm('Stop this optimization? The configs measured so far are kept.')) return
    try {
      const r = await fetch(`${API_BASE}/api/eval/optimizations/${study.id}/cancel`, { method: 'POST' })
      if (!r.ok) { setError(await detail(r)); return }
      const next: OptimizeStudy = await r.json()
      setStudy(next)
      setPast((list) => list.map((p) => (p.id === next.id ? next : p)))
    } catch {
      setError('Backend unreachable')
    }
  }

  const apply = async () => {
    if (!study) return
    if (!window.confirm('Write these models into the pipeline\'s draft? A published pipeline goes back to draft; publish again to use them.')) return
    const r = await fetch(`${API_BASE}/api/eval/optimizations/${study.id}/apply`, { method: 'POST' })
    if (!r.ok) { setError(await detail(r)); return }
    setApplied(await r.json())
  }

  const res = study?.result
  const slotByKey: Record<string, OptimizeSlot> = Object.fromEntries((res?.slots ?? slots).map((s) => [s.key, s]))
  const changes = (a: Assignment) => Object.entries(a).map(([key, c]) =>
    `${slotByKey[key]?.label ?? key} → ${c.provider}/${c.model}`)
  const metric = (c: OptimizeConfig) => (res?.objective === 'latency' ? `${Math.round(c.avg_latency_ms)} ms` : usd(c.cost_per_case_usd))
  const saving = res?.best && res.baseline && !same(res.best.assignment, res.baseline.assignment)
    ? 1 - (res.objective === 'latency'
      ? res.best.avg_latency_ms / (res.baseline.avg_latency_ms || 1)
      : res.best.cost_per_case_usd / (res.baseline.cost_per_case_usd || 1))
    : 0

  // Saved models that pass nothing give the search no quality signal: any model "keeps" 0%
  const noSignal = !!res?.baseline && res.baseline.cases > 0 && res.baseline.pass_rate === 0

  return (
    <div className="eval-tab-body opt-layout">
      <div className="eval-run-config opt-setup">
        <div className="eval-label">
          Tries other models on each LLM node and keeps the cheapest set that still passes your dataset.
          Every option runs the whole pipeline, so a cheap model that makes later steps work harder is charged for it.
        </div>

        <div className="eval-field">
          <label className="eval-label" htmlFor="opt-dataset">Dataset</label>
          <select id="opt-dataset" className="eval-select" value={dataset ? datasetId : ''}
            onChange={(e) => selectDataset(e.target.value)}>
            <option value="">— select dataset —</option>
            {linked.map((ds) => (
              <option key={ds.id} value={ds.id}>{ds.name} · {pipelineLabel(ds.app_id, ds.app_version)} ({ds.case_count} cases)</option>
            ))}
          </select>
          {datasets.length > linked.length && (
            <span className="opt-hint">Only datasets linked to a pipeline are listed.</span>
          )}
        </div>

        {dataset && (
          <div className="opt-slots">
            <div className="eval-label">Nodes to optimize ({chosen.length} of {slots.length})</div>
            {slots.map((s) => (
              <div key={s.key} className="opt-slot">
                <input type="checkbox" aria-label={`Optimize ${s.label}`} checked={!skipped.has(s.key)}
                  onChange={() => setSkipped((prev) => {
                    const next = new Set(prev)
                    if (next.has(s.key)) next.delete(s.key); else next.add(s.key)
                    return next
                  })} />
                <span className="opt-slot-label">{s.label}</span>
                <span className="opt-slot-model">{s.provider}/{s.model}</span>
                <span className="opt-hint">{s.source}</span>
              </div>
            ))}
            {!slots.length && !slotError && <span className="opt-hint">Loading…</span>}
            {slotError && <div className="eval-warn">⚠ {slotError}</div>}
            {slots.length > 1 && <span className="opt-hint">Unticked nodes keep their saved model.</span>}
          </div>
        )}

        <div className="opt-row">
          <div className="eval-field">
            <label className="eval-label" htmlFor="opt-objective">Optimize for</label>
            <select id="opt-objective" className="eval-select" value={objective} onChange={(e) => setObjective(e.target.value as 'cost' | 'latency')}>
              <option value="cost">Lowest cost per case</option>
              <option value="latency">Lowest latency</option>
            </select>
          </div>
          <div className="eval-field">
            <label className="eval-label" htmlFor="opt-scorer">Scorer</label>
            <select id="opt-scorer" className="eval-select" value={scorer} onChange={(e) => setScorer(e.target.value)}>
              <option value="contains">Contains</option>
              <option value="exact">Exact</option>
              <option value="llm_judge">LLM Judge (costs tokens)</option>
            </select>
          </div>
          <div className="eval-field">
            <label className="eval-label" htmlFor="opt-tolerance">Pass rate it may lose</label>
            <span className="opt-inline">
              <input id="opt-tolerance" type="number" min={0} max={100} className="eval-count-input" value={tolerancePct}
                onChange={(e) => setTolerancePct(Math.max(0, Math.min(100, Number(e.target.value) || 0)))} /> points
            </span>
          </div>
          <div className="eval-field">
            <label className="eval-label" htmlFor="opt-screen">Screen on first</label>
            <span className="opt-inline">
              <input id="opt-screen" type="number" min={0} className="eval-count-input" value={screenCases}
                onChange={(e) => setScreenCases(Math.max(0, Number(e.target.value) || 0))} /> cases (0 = off)
            </span>
            {screenCases > 0 && dataset && screenCases >= dataset.case_count && (
              <span className="opt-hint">Screening needs fewer cases than the {dataset.case_count} in the dataset, so it stays off.</span>
            )}
          </div>
          <div className="eval-field">
            <label className="eval-label" htmlFor="opt-max">Max configs</label>
            <input id="opt-max" type="number" min={1} max={500} className="eval-count-input" value={maxConfigs}
              onChange={(e) => setMaxConfigs(Math.max(1, Math.min(500, Number(e.target.value) || 1)))} />
          </div>
          <div className="eval-field">
            <label className="eval-label" htmlFor="opt-parallel">Cases at once</label>
            <input id="opt-parallel" type="number" min={1} max={16} className="eval-count-input" value={parallel}
              title="Runs this many cases of a config at the same time. Higher is faster but may hit provider rate limits."
              onChange={(e) => setParallel(Math.max(1, Math.min(16, Number(e.target.value) || 1)))} />
          </div>
        </div>

        <div className="eval-field">
          <span className="eval-label">Models to try ({picked.size} picked)</span>
          <div className="opt-candidates">
            {shownProviders.map((p) => (
              <fieldset key={p.id} className="opt-provider">
                <legend>{p.name}</legend>
                {p.models.map((m) => {
                  const key = `${p.id}/${m}`
                  return (
                    <label key={key} className="opt-model">
                      <input type="checkbox" checked={picked.has(key)} onChange={() => toggle(key)} /> {m}
                    </label>
                  )
                })}
              </fieldset>
            ))}
          </div>
          {keyed.length > 0 && keyed.length < providers.length && (
            <button type="button" className="opt-link" onClick={() => setAllProviders(!allProviders)}>
              {allProviders ? 'Only providers with an API key' : `Show all providers (${providers.length - keyed.length} more without a key)`}
            </button>
          )}
          <span className="opt-hint">Models without an API key in Settings are skipped. A node's own model is never re-tried.</span>
        </div>

        {dataset && candidates.length > 0 && slots.length > 0 && (
          <div className="opt-hint">
            Up to {estimate.configs} configs · about {estimate.runs} pipeline runs — each one is a real, billed run.
          </div>
        )}
        <button type="button" className="eval-run-btn" onClick={start}
          disabled={starting || running || !dataset || !dataset.case_count || !chosen.length || !candidates.length}>
          {running ? '⏳ Optimizing…' : '⚡ Optimize models'}
        </button>
        {error && <div className="eval-warn" role="alert">⚠ {error}</div>}
      </div>

      <div className="opt-results">
      {!study && <div className="eval-empty">Pick a dataset and the models to try, then start — or open a past optimization below.</div>}
      {study && (
        <div className="opt-study" ref={studyRef}>
          <StudyStatus study={study} changes={changes} slots={res?.slots ?? slots} onCancel={cancel} />
          {!running && (
            <div className="opt-actions">
              <button type="button" className="eval-action-btn" disabled={!canRerun(study) || starting}
                title={canRerun(study) ? 'Start it again with the same settings' : 'Its dataset was deleted or unlinked'}
                onClick={() => rerun(study)}>↻ Re-run</button>
              <button type="button" className="eval-action-btn" disabled={!canRerun(study)}
                title="Put these settings in the form to change the models and start again"
                onClick={() => loadSettings(study)}>✎ Edit &amp; re-run</button>
            </div>
          )}
          {noSignal && (
            <div className="eval-warn" role="alert">
              ⚠ The saved models pass none of the cases, so this result says nothing about quality — don't apply it.
              Check the expected outputs, or re-run with the LLM Judge scorer.
            </div>
          )}
          {res?.warnings?.map((w) => <div key={w} className="eval-warn">⚠ {w}</div>)}
          {[...new Set((res?.tried ?? []).map((c) => c.first_error).filter(Boolean))].map((e) => (
            <div key={e} className="eval-warn">⚠ Some cases failed: {e}</div>
          ))}

          {res?.baseline && res.best && (
            <div className="opt-summary">
              <div className="opt-stat">
                <span className="opt-stat-label">Saved models</span>
                <span className="opt-stat-value">{metric(res.baseline)}</span>
                <span className="opt-hint">{pct(res.baseline.pass_rate)} pass</span>
              </div>
              <div className={`opt-stat${saving > 0 ? ' opt-stat--best' : ''}`}>
                <span className="opt-stat-label">{saving > 0 && study.status === 'done' ? 'Recommended' : 'Best so far'}</span>
                <span className="opt-stat-value">{metric(res.best)}</span>
                <span className="opt-hint">{pct(res.best.pass_rate)} pass{saving > 0 ? ` · ${Math.round(saving * 100)}% ${res.objective === 'latency' ? 'faster' : 'cheaper'}` : ''}</span>
              </div>
              <div className="opt-changes">
                {Object.keys(res.best.assignment).length
                  ? changes(res.best.assignment).map((c) => <div key={c}>{c}</div>)
                  : <div className="opt-hint">{running ? 'No winner yet — still trying models.' : 'No model beat the saved ones within the tolerance.'}</div>}
              </div>
            </div>
          )}

          {study.status === 'done' && !noSignal && res?.best && Object.keys(res.best.assignment).length > 0 && !applied && (
            <button type="button" className="eval-action-btn eval-action-btn--primary" onClick={apply}>Apply to draft</button>
          )}
          {applied && (
            <div className="eval-generate-msg">
              {applied.applied.length ? `Applied to the draft: ${applied.applied.map((a) => `${a.label} → ${a.model}`).join(', ')}.` : 'Nothing applied.'}
              {applied.skipped.map((s) => <div key={s.key}>Not applied: {s.label} ({s.reason}) — edit that pipeline and re-publish.</div>)}
            </div>
          )}

          {(!!res?.tried.length || !!res?.current) && (
            <table className="opt-table">
              <thead>
                <tr><th>Config</th><th>Changes</th><th>Cases</th><th>Pass</th><th>Cost / case</th><th>Latency</th><th>Keeps target</th></tr>
              </thead>
              <tbody>
                {res.tried.map((c, i) => {
                  const isBest = !!res.best && same(c.assignment, res.best.assignment) && c.phase !== 'screen'
                  const open = openConfig?.study === study.id && openConfig.index === i
                  return (
                    <Fragment key={i}>
                    <tr className={`opt-trow${isBest ? ' opt-trow--best' : ''}${open ? ' opt-trow--open' : ''}`}
                      onClick={() => setOpenConfig(open ? null : { study: study.id, index: i })}>
                      <td><span className="opt-caret">{open ? '▾' : '▸'}</span> {PHASE_LABEL[c.phase]}{isBest ? ' ★' : ''}</td>
                      <td>{changes(c.assignment).join(', ') || '—'}</td>
                      <td>{c.cases}</td>
                      <td title={c.first_error ?? undefined}>{pct(c.pass_rate)}{c.errors ? ` · ${c.errors} err` : ''}</td>
                      <td>{usd(c.cost_per_case_usd)}</td>
                      <td>{Math.round(c.avg_latency_ms)} ms</td>
                      <td>{c.meets_target === null ? '' : c.meets_target ? '✓' : '✗'}</td>
                    </tr>
                    {open && <tr><td colSpan={7}><ConfigCases studyId={study.id} index={i} /></td></tr>}
                    </Fragment>
                  )
                })}
                {running && res.current && (() => {
                  const cur = res.current
                  const index = cur.index ?? res.tried.length
                  const open = openConfig?.study === study.id && openConfig.index === index
                  const n = Math.max(1, cur.cases_done)
                  return (
                    <Fragment key="running">
                      <tr className={`opt-trow opt-trow--running${open ? ' opt-trow--open' : ''}`}
                        onClick={() => setOpenConfig(open ? null : { study: study.id, index })}>
                        <td><span className="opt-caret">{open ? '▾' : '▸'}</span> {PHASE_LABEL[cur.phase]} · running</td>
                        <td>{changes(cur.assignment).join(', ') || '—'}</td>
                        <td>{cur.cases_done} / {cur.cases_total}</td>
                        <td>{cur.cases_done ? pct((cur.passed ?? 0) / n) : '…'}</td>
                        <td>{cur.cases_done ? usd((cur.cost_usd ?? 0) / n) : '…'}</td>
                        <td>{cur.cases_done ? `${Math.round((cur.latency_ms ?? 0) / n)} ms` : '…'}</td>
                        <td />
                      </tr>
                      {open && <tr><td colSpan={7}><ConfigCases studyId={study.id} index={index} refreshKey={study.updated_at} /></td></tr>}
                    </Fragment>
                  )
                })()}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div className="eval-field">
        <span className="eval-label">{dataset ? 'Optimizations of this pipeline' : 'Recent optimizations'} ({past.length})</span>
        {!past.length && <span className="opt-hint">None yet.</span>}
        {past.map((p) => {
          const best = p.result?.best
          const base = p.result?.baseline
          const moved = best && base
            ? (p.result?.objective === 'latency'
              ? `${Math.round(base.avg_latency_ms)} → ${Math.round(best.avg_latency_ms)} ms`
              : `${usd(base.cost_per_case_usd)} → ${usd(best.cost_per_case_usd)}`)
            : ''
          const picked = Object.values(best?.assignment ?? {}).map((c) => c.model).join(', ')
          return (
            <div key={p.id} className={`opt-past${study?.id === p.id ? ' opt-past--active' : ''}`}>
              <button type="button" className="opt-past-main" onClick={() => openStudy(p)}>
                <span className={`opt-pill opt-pill--${normalized(p).status}`}>{STATUS_LABEL[normalized(p).status]}</span>
                <span className="opt-past-title">{datasetName(p.dataset_id)} · {pipelineLabel(p.app_id, p.app_version)}</span>
                <span className="opt-hint">
                  {when(p.created_at)} · {p.request.candidates?.length ?? 0} models · {p.request.scorer ?? 'contains'}
                  {base?.pass_rate === 0 ? ' · no quality signal' : ''}
                  {moved ? ` · ${moved}` : ''}
                  {picked ? ` (${picked})` : ''}
                </span>
              </button>
              <button type="button" className="eval-action-btn" aria-label={`Re-run ${when(p.created_at)}`}
                disabled={!canRerun(p) || starting || running} onClick={() => rerun(p)}>↻</button>
              <button type="button" className="eval-action-btn" aria-label={`Edit and re-run ${when(p.created_at)}`}
                disabled={!canRerun(p)} onClick={() => loadSettings(p)}>✎</button>
            </div>
          )
        })}
      </div>
      </div>
    </div>
  )
}


/** Status badge, progress bar and the config being tried right now. */
function StudyStatus({ study: raw, changes, slots, onCancel }: {
  study: OptimizeStudy; changes: (a: Assignment) => string[]; slots: OptimizeSlot[]; onCancel: () => void
}) {
  const study = normalized(raw)
  const res = study.result
  const cands = study.request.candidates ?? []
  const screen = study.request.screen_cases ?? 0
  // the swaps the search will try: each candidate on each node, except a node's own model
  const swaps = slots.reduce((n, s) => n + cands.filter((c) =>
    !(c.provider === s.provider.toLowerCase() && c.model === s.model)).length, 0)
  const planned = Math.max(1, res?.planned_configs ?? res?.max_configs ?? 1)
  const cur = res?.current
  const done = study.status !== 'queued' && study.status !== 'running'
  const fraction = study.status === 'done' ? 1
    : Math.min(1, ((res?.configs_run ?? 0) + (cur ? cur.cases_done / Math.max(1, cur.cases_total) : 0)) / planned)
  // updated_at moves after every case, so a running study's elapsed time is current as of the last poll
  const elapsedMs = utc(study.updated_at ?? study.created_at).getTime() - utc(study.created_at).getTime()
  const elapsed = duration(elapsedMs)
  // Time left: average time per case so far × the cases still planned (screens make it an upper bound)
  const perConfig = res?.baseline?.cases ?? cur?.cases_total ?? 0
  const casesDone = (res?.tried ?? []).reduce((n, c) => n + c.cases, 0) + (cur?.cases_done ?? 0)
  const casesLeft = Math.max(0, planned - (res?.configs_run ?? 0) - (cur ? 1 : 0)) * perConfig
    + (cur ? cur.cases_total - cur.cases_done : 0)
  const left = study.status === 'running' && casesDone > 0 ? duration((elapsedMs / casesDone) * casesLeft) : null

  return (
    <div className={`opt-status-card opt-status-card--${study.status}`} role="status">
      <div className="opt-status-head">
        <span className={`opt-pill opt-pill--${study.status}`}>
          {!done && <span className="opt-spinner" aria-hidden="true" />}{STATUS_LABEL[study.status]}
        </span>
        <span className="opt-status-text">
          {study.status === 'queued' && 'Waiting for a worker…'}
          {study.status === 'running' && `${res?.configs_run ?? 0} of ~${planned} configs`}
          {study.status === 'done' && `${res?.configs_run ?? 0} configs${res?.truncated ? ' — stopped at the config limit' : ''}`}
          {study.status === 'failed' && 'Stopped'}
          {study.status === 'cancelled' && `Stopped by you after ${res?.configs_run ?? 0} configs`}
        </span>
        <span className="opt-hint">
          {done ? `took ${elapsed}` : elapsed}{left ? ` · ~${left} left` : ''} · started {when(study.created_at)}
        </span>
        {!done && <button type="button" className="eval-action-btn opt-cancel" onClick={onCancel}>■ Cancel</button>}
      </div>
      {!done && slots.length > 0 && (
        <div className="opt-hint">
          Plan: saved models → {swaps} single swap{swaps === 1 ? '' : 's'} ({slots.length} node{slots.length === 1 ? '' : 's'} × {cands.length} model{cands.length === 1 ? '' : 's'}{screen ? `, each screened on ${screen} cases first` : ''})
          {slots.length > 1 ? ' → combine the ones that keep the pass rate' : ''}. Each case runs the whole pipeline.
        </div>
      )}
      {study.status !== 'failed' && (
        <div className="opt-progress" aria-label="Progress">
          <div className="opt-progress-bar" style={{ width: `${Math.round(fraction * 100)}%` }} />
        </div>
      )}
      {study.status === 'running' && cur && (
        <div className="opt-status-current">
          Trying {cur.phase === 'baseline' ? 'the saved models' : changes(cur.assignment).join(', ')}
          {cur.phase === 'screen' ? ' (screen)' : ''} · case {Math.min(cur.cases_done + 1, cur.cases_total)} of {cur.cases_total}
          {cur.cases_done > 0 && cur.passed !== undefined
            && ` · ${cur.passed}/${cur.cases_done} passing so far · ${usd((cur.cost_usd ?? 0) / cur.cases_done)}/case`}
        </div>
      )}
      {study.status === 'failed' && <div className="eval-detail-error">{study.error}</div>}
    </div>
  )
}


/** The cases of one config: what the pipeline answered and how it scored. Live while ``refreshKey`` changes. */
function ConfigCases({ studyId, index, refreshKey }: { studyId: string; index: number; refreshKey?: string }) {
  const [cases, setCases] = useState<OptimizeCase[] | null>(null)
  const [failedOnly, setFailedOnly] = useState(false)
  useEffect(() => {
    fetch(`${API_BASE}/api/eval/optimizations/${studyId}/cases?config=${index}`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setCases)
      .catch(() => setCases([]))
  }, [studyId, index, refreshKey])

  if (cases === null) return <div className="opt-hint">Loading cases…</div>
  if (!cases.length) return <div className="opt-hint">No cases recorded for this config (studies before per-case results only kept totals).</div>
  const shown = failedOnly ? cases.filter((c) => !c.passed) : cases
  return (
    <div className="opt-cases">
      <label className="opt-hint opt-inline">
        <input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} />
        Failed only ({cases.filter((c) => !c.passed).length} of {cases.length})
      </label>
      {shown.map((c) => (
        <div key={c.case_id} className={`opt-case${c.passed ? '' : ' opt-case--fail'}`}>
          <span className="opt-case-mark" aria-label={c.passed ? 'passed' : 'failed'}>{c.passed ? '✓' : '✗'}</span>
          <div className="opt-case-body">
            <div className="opt-case-prompt">{c.prompt}</div>
            <div className="opt-case-answer">{c.error ? <span className="eval-detail-error">{c.error}</span> : c.output || '(empty)'}</div>
            {c.expected_output && <div className="opt-hint">Expected: {c.expected_output}</div>}
          </div>
          <span className="opt-case-meta">{Math.round(c.score * 100)}% · {usd(c.cost_usd)} · {c.latency_ms} ms</span>
        </div>
      ))}
    </div>
  )
}
