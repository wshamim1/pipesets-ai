import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../types'
import { useCredentials } from '../context/CredentialsContext'
import { browserProviderKeys } from '../utils/providerKeys'

interface Gate {
  app_id: string
  dataset_id: string
  dataset_name: string | null
  case_count: number
  scorer: 'exact' | 'contains' | 'llm_judge'
  min_pass_rate: number
  no_regression: boolean
  regression_tolerance: number
  mode: 'block' | 'warn'
  enabled: boolean
  timeout_ms: number
}

/** Result of a gate check — also the `gate` in a blocked publish's 409 detail. */
export interface GateResult {
  status: 'passed' | 'failed' | 'warned' | 'overridden' | 'error'
  mode: 'block' | 'warn'
  reasons: string[]
  pass_rate?: number
  passed?: number
  total?: number
  baseline?: { version: number; pass_rate: number } | null
}

interface Dataset {
  id: string
  name: string
  app_id: string | null
  case_count: number
}

const SCORERS: { id: Gate['scorer']; label: string }[] = [
  { id: 'contains', label: 'Contains expected' },
  { id: 'exact', label: 'Exact match' },
  { id: 'llm_judge', label: 'LLM judge' },
]

const pct = (x: number) => `${Math.round(x * 100)}%`

async function errorText(r: Response): Promise<string> {
  const d = await r.json().catch(() => ({}))
  if (typeof d.detail === 'string') return d.detail
  if (d.detail?.message) return d.detail.message
  return r.statusText
}

/** One line for a gate result, e.g. "9/10 passed (90%) · v3 was 100%". */
export function describeGateResult(g: GateResult): string {
  if (g.total === undefined) return g.reasons.join('; ')
  const base = g.baseline ? ` · v${g.baseline.version} was ${pct(g.baseline.pass_rate)}` : ''
  return `${g.passed}/${g.total} passed (${pct(g.pass_rate ?? 0)})${base}`
}

function GateForm({ appId, initial, onCancel, onSaved }: {
  appId: string
  initial: Gate | null
  onCancel: () => void
  onSaved: () => void
}) {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null)
  const [f, setF] = useState({
    dataset_id: initial?.dataset_id ?? '',
    scorer: initial?.scorer ?? 'contains',
    min_pct: String(Math.round((initial?.min_pass_rate ?? 0.8) * 100)),
    no_regression: initial?.no_regression ?? true,
    tol_pct: String(Math.round((initial?.regression_tolerance ?? 0) * 100)),
    mode: initial?.mode ?? 'block',
  })
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }))

  useEffect(() => {
    fetch(`${API_BASE}/api/eval/datasets`)
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: Dataset[]) => {
        // This pipeline's datasets first
        setDatasets([...rows.filter((d) => d.app_id === appId), ...rows.filter((d) => d.app_id !== appId)])
        if (!initial && rows.length) {
          const own = rows.find((d) => d.app_id === appId && d.case_count > 0)
          if (own) set('dataset_id', own.id)
        }
      })
      .catch(() => setDatasets([]))
  }, [appId, initial])

  const clampPct = (s: string) => Math.min(100, Math.max(0, parseFloat(s) || 0)) / 100

  const save = async () => {
    if (!f.dataset_id) { setError('Pick an eval dataset.'); return }
    setSaving(true)
    setError(null)
    try {
      const r = await fetch(`${API_BASE}/api/apps/${encodeURIComponent(appId)}/publish-gate`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dataset_id: f.dataset_id, scorer: f.scorer, min_pass_rate: clampPct(f.min_pct),
          no_regression: f.no_regression, regression_tolerance: clampPct(f.tol_pct), mode: f.mode,
          enabled: initial?.enabled ?? true, timeout_ms: initial?.timeout_ms ?? 120000,
        }),
      })
      if (!r.ok) { setError(await errorText(r)); return }
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="sched-form">
      <label className="sched-field">
        <span>Dataset</span>
        <select className="ops-select" value={f.dataset_id} onChange={(e) => set('dataset_id', e.target.value)}>
          <option value="">{datasets === null ? 'Loading…' : 'Select an eval dataset…'}</option>
          {(datasets ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name} ({d.case_count} case{d.case_count !== 1 ? 's' : ''}){d.app_id === appId ? '' : ' · other pipeline'}
            </option>
          ))}
        </select>
      </label>
      {datasets?.length === 0 && (
        <p className="sched-muted">No eval datasets yet — create one in the Lab, then come back.</p>
      )}
      <label className="sched-field">
        <span>Scorer</span>
        <select className="ops-select" value={f.scorer} onChange={(e) => set('scorer', e.target.value as Gate['scorer'])}>
          {SCORERS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
      </label>
      <div className="sched-advanced-row">
        <label className="sched-inline">
          Require
          <input className="sched-input sched-input--num" type="number" min={0} max={100} value={f.min_pct}
                 onChange={(e) => set('min_pct', e.target.value)} />
          % of cases to pass
        </label>
      </div>
      <div className="sched-advanced-row">
        <label className="sched-inline">
          <input type="checkbox" checked={f.no_regression} onChange={(e) => set('no_regression', e.target.checked)} />
          Don't score lower than the live version
        </label>
        {f.no_regression && (
          <label className="sched-inline">
            tolerance
            <input className="sched-input sched-input--num" type="number" min={0} max={100} value={f.tol_pct}
                   onChange={(e) => set('tol_pct', e.target.value)} />
            %
          </label>
        )}
      </div>
      <label className="sched-field">
        <span>On failure</span>
        <select className="ops-select" value={f.mode} onChange={(e) => set('mode', e.target.value as Gate['mode'])}>
          <option value="block">Block the publish (can be overridden)</option>
          <option value="warn">Publish, but flag the version</option>
        </select>
      </label>
      {error && <div className="sched-error">{error}</div>}
      <div className="sched-form-actions">
        <button type="button" className="docs-btn" onClick={onCancel} disabled={saving}>Cancel</button>
        <button type="button" className="docs-btn docs-btn--primary" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : initial ? 'Save gate' : 'Add gate'}
        </button>
      </div>
    </div>
  )
}

/** Details tab: the pipeline's eval gate — every publish must pass it first. */
export function PublishGateCard({ appId }: { appId: string }) {
  const { resolveApiKey } = useCredentials()
  const [gate, setGate] = useState<Gate | null | undefined>(undefined)   // undefined = loading
  const [editing, setEditing] = useState(false)
  const [checking, setChecking] = useState(false)
  const [result, setResult] = useState<GateResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    fetch(`${API_BASE}/api/apps/${encodeURIComponent(appId)}/publish-gate`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setGate)
      .catch(() => setGate(null))
  }, [appId])

  useEffect(() => { load(); setEditing(false); setResult(null); setError(null) }, [load])

  const call = async (path: string, init: RequestInit) => {
    try {
      const r = await fetch(`${API_BASE}/api/apps/${encodeURIComponent(appId)}/publish-gate${path}`, init)
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setError(typeof d.detail === 'string' ? d.detail : d.detail?.message ?? r.statusText); return null }
      setError(null)
      return d
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return null
    }
  }

  const checkNow = async () => {
    setChecking(true)
    setResult(null)
    const d = await call('/check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider_keys: browserProviderKeys(resolveApiKey) }),
    })
    if (d) setResult(d)
    setChecking(false)
  }

  const toggle = async () => {
    if (!gate) return
    const body = {
      dataset_id: gate.dataset_id, scorer: gate.scorer, min_pass_rate: gate.min_pass_rate,
      no_regression: gate.no_regression, regression_tolerance: gate.regression_tolerance, mode: gate.mode,
      timeout_ms: gate.timeout_ms, enabled: !gate.enabled,
    }
    if (await call('', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })) load()
  }

  const remove = async () => {
    if (!window.confirm('Remove the eval gate? Publishing will no longer run the dataset first.')) return
    if (await call('', { method: 'DELETE' })) { setResult(null); load() }
  }

  return (
    <section className="overview-card">
      <div className="overview-card-head">
        <h3 className="overview-title">Eval gate</h3>
        {gate && <span className="overview-muted">{gate.enabled ? (gate.mode === 'block' ? 'blocks publish' : 'warns') : 'off'}</span>}
      </div>

      {gate === undefined && <div className="overview-muted">Loading…</div>}

      {editing && gate !== undefined && (
        <GateForm appId={appId} initial={gate} onCancel={() => setEditing(false)}
                  onSaved={() => { setEditing(false); setResult(null); load() }} />
      )}

      {!editing && gate === null && (
        <>
          <div className="overview-muted">
            Run an eval dataset before every publish, and stop a version that scores below your bar or below the
            live version.
          </div>
          <div className="sched-actions">
            <button type="button" className="docs-btn docs-btn--primary" onClick={() => setEditing(true)}>Set up gate</button>
          </div>
        </>
      )}

      {!editing && gate && (
        <>
          <div className="overview-run-meta">
            <span>{gate.dataset_name ?? 'Deleted dataset'} · {gate.case_count} case{gate.case_count !== 1 ? 's' : ''}</span>
            <span>{SCORERS.find((s) => s.id === gate.scorer)?.label}</span>
          </div>
          <div className="overview-run-meta">
            <span>Needs ≥ {pct(gate.min_pass_rate)}</span>
            {gate.no_regression && (
              <span>no regression{gate.regression_tolerance ? ` (±${pct(gate.regression_tolerance)})` : ''}</span>
            )}
          </div>
          {gate.case_count === 0 && <div className="sched-error sched-error--inline">The dataset has no cases — publishing will be blocked.</div>}
          {result && (
            <div className={result.status === 'passed' ? 'sched-note' : 'sched-error'}>
              <strong>{result.status === 'passed' ? '✓ Draft passes' : '✗ Draft fails'}</strong> — {describeGateResult(result)}
              {result.reasons.map((r) => <div key={r}>{r}</div>)}
            </div>
          )}
          {error && <div className="sched-error">{error}</div>}
          <div className="sched-actions">
            <button type="button" className="docs-btn" onClick={checkNow} disabled={checking || !gate.case_count}>
              {checking ? 'Running…' : '▶ Check draft'}
            </button>
            <button type="button" className="docs-btn" onClick={() => setEditing(true)}>Edit</button>
            <button type="button" className="docs-btn" onClick={toggle}>{gate.enabled ? 'Turn off' : 'Turn on'}</button>
            <button type="button" className="docs-btn sched-delete" onClick={remove}>Remove</button>
          </div>
        </>
      )}
    </section>
  )
}
