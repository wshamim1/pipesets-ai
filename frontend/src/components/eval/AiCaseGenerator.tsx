import { useEffect, useState } from 'react'
import { API_BASE } from '../../types'
import type { AppRecord } from '../../types'
import { useCredentials } from '../../context/CredentialsContext'
import { fetchAppVersions } from '../../utils/publishedApps'
import type { AppVersionInfo } from '../../utils/publishedApps'

interface DraftCase {
  prompt: string
  expected_output: string
  tags: string[]
  keep: boolean
}

interface GenerateResult {
  model_used: string
  skipped_duplicates: number
  pipeline: { name: string; version: number; sub_pipelines: string[]; warnings: string[] }
}

export interface DatasetRef {
  id: string
  name: string
  app_id: string | null
  app_version?: number
}

interface Props {
  apps: AppRecord[]
  datasets: DatasetRef[]
  /** Called after cases are saved, with the dataset they went into and a status line. */
  onSaved: (datasetId: string, message: string) => void
  /** Generate for this dataset: "more" appends new cases, "regenerate" replaces its AI cases. */
  dataset?: DatasetRef
  mode?: 'more' | 'regenerate'
  onClose?: () => void
  defaultOpen?: boolean
}

const NEW_DATASET = '__new__'

/** Pick a saved pipeline (and version), let AI draft test cases, review them, then save. */
export function AiCaseGenerator({ apps, datasets, onSaved, dataset, mode, onClose, defaultOpen = true }: Props) {
  const { resolveApiKey } = useCredentials()
  const [open, setOpen] = useState(defaultOpen)
  const [appId, setAppId] = useState(dataset?.app_id ?? '')
  const [versions, setVersions] = useState<AppVersionInfo[]>([])
  const [version, setVersion] = useState(dataset?.app_version ?? 0)
  const [count, setCount] = useState(10)
  const [focus, setFocus] = useState('')
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<DraftCase[]>([])
  const [result, setResult] = useState<GenerateResult | null>(null)
  const [target, setTarget] = useState(dataset?.id ?? NEW_DATASET)
  const [newName, setNewName] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => { if (!defaultOpen) setOpen(false) }, [defaultOpen])

  const app = apps.find((a) => a.id === appId)
  const datasetsFor = (id: string) => datasets.filter((d) => d.app_id === id)

  useEffect(() => {
    setVersions([])
    if (!appId) return
    let cancelled = false
    fetchAppVersions(appId)
      .then((v) => {
        if (cancelled) return
        setVersions(v)
        // keep a dataset's linked version; otherwise default to the latest published one
        if (!dataset?.app_version) setVersion(v[0]?.version ?? 0)
      })
      .catch(() => { if (!cancelled) setVersion(0) })
    return () => { cancelled = true }
  }, [appId, dataset?.app_version])

  const pickApp = (id: string) => {
    setAppId(id)
    setDrafts([])
    setResult(null)
    // Already has a dataset for this pipeline? Default to adding there instead of a near-duplicate dataset.
    if (!dataset) setTarget(datasetsFor(id)[0]?.id ?? NEW_DATASET)
  }

  const targetId = dataset?.id ?? (target === NEW_DATASET ? undefined : target)

  const generate = async () => {
    if (!appId) return
    setGenerating(true)
    setError(null)
    try {
      const r = await fetch(`${API_BASE}/api/eval/generate-cases`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          app_id: appId, version, count, instructions: focus,
          dataset_id: targetId,
          // regenerating replaces the AI cases, so only manual ones need avoiding
          avoid: mode === 'regenerate' ? 'manual' : 'all',
          provider_keys: {
            openai: resolveApiKey('openai'), anthropic: resolveApiKey('anthropic'),
            groq: resolveApiKey('groq'), gemini: resolveApiKey('gemini'), mistral: resolveApiKey('mistral'),
          },
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setError(typeof d.detail === 'string' ? d.detail : r.statusText); return }
      setDrafts((d.cases ?? []).map((c: Omit<DraftCase, 'keep'>) => ({ ...c, keep: true })))
      setResult({ model_used: d.model_used, pipeline: d.pipeline, skipped_duplicates: d.skipped_duplicates ?? 0 })
      setNewName(`${d.pipeline.name}${d.pipeline.version ? ` v${d.pipeline.version}` : ''} — AI cases`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setGenerating(false)
    }
  }

  const updateDraft = (i: number, patch: Partial<DraftCase>) =>
    setDrafts((prev) => prev.map((c, j) => (j === i ? { ...c, ...patch } : c)))

  const kept = drafts.filter((c) => c.keep && c.prompt.trim())

  const save = async () => {
    if (!kept.length) return
    setSaving(true)
    setError(null)
    try {
      let datasetId = targetId
      if (!datasetId) {
        const r = await fetch(`${API_BASE}/api/eval/datasets`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: newName.trim() || 'AI cases',
            description: `Generated by ${result?.model_used ?? 'AI'}${focus.trim() ? ` · focus: ${focus.trim()}` : ''}`,
            app_id: appId,
            app_version: version,
          }),
        })
        if (!r.ok) { setError('Could not create dataset'); return }
        datasetId = (await r.json()).id as string
      }
      const r = await fetch(`${API_BASE}/api/eval/datasets/${datasetId}/cases/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          replace: mode === 'regenerate' ? 'ai' : 'none',
          cases: kept.map(({ prompt, expected_output, tags }) => ({ prompt, expected_output, tags, source: 'ai' })),
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setError('Could not save cases'); return }
      const parts = [`✓ Saved ${d.cases_created} case${d.cases_created === 1 ? '' : 's'}`]
      if (d.replaced) parts.push(`replaced ${d.replaced} earlier AI case${d.replaced === 1 ? '' : 's'}`)
      if (d.skipped_duplicates) parts.push(`skipped ${d.skipped_duplicates} already in the dataset`)
      setDrafts([])
      setResult(null)
      onSaved(datasetId!, parts.join(' · '))
    } finally {
      setSaving(false)
    }
  }

  const title = mode === 'regenerate' ? '↻ Regenerate AI cases' : mode === 'more' ? '✨ Generate more cases' : '✨ Generate test cases with AI'

  return (
    <div className={`eval-form-card ai-gen-card${dataset ? ' ai-gen-card--inline' : ''}`}>
      {onClose ? (
        <div className="ai-gen-header">
          <strong>{title}</strong>
          <button type="button" className="eval-cancel-btn" onClick={onClose}>Close</button>
        </div>
      ) : (
        <button
          type="button"
          className="ai-gen-header ai-gen-header--toggle"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          <strong><span className="ds-caret">{open ? '▾' : '▸'}</span> {title}</strong>
          <span className="eval-label">{open ? 'Hide' : 'Show'}</span>
        </button>
      )}
      {mode === 'regenerate' && (
        <div className="eval-label">Replaces this dataset's AI-generated cases. Manual and trace cases are kept.</div>
      )}

      {open && (
        <>
          <div className="ai-gen-row">
            <label className="eval-field">
              <span className="eval-label">Pipeline</span>
              <select className="eval-select" value={appId} onChange={(e) => pickApp(e.target.value)}>
                <option value="">Select a pipeline…</option>
                {apps.map((a) => {
                  const n = datasetsFor(a.id).length
                  return (
                    <option key={a.id} value={a.id}>
                      {a.name}{a.version > 0 ? ` — latest v${a.version}` : ' (draft)'}
                      {!dataset && n ? ` · ${n} dataset${n === 1 ? '' : 's'}` : ''}
                    </option>
                  )
                })}
              </select>
            </label>
            <label className="eval-field">
              <span className="eval-label">Version</span>
              <select className="eval-select" value={version} disabled={!appId} onChange={(e) => setVersion(Number(e.target.value))}>
                {versions.map((v) => (
                  <option key={v.version} value={v.version}>
                    v{v.version}{v.version === versions[0]?.version ? ' (latest)' : ''} · {v.node_count} nodes
                  </option>
                ))}
                <option value={0}>Saved draft{app?.status === 'draft' ? ' (being edited)' : ''}</option>
              </select>
            </label>
            <label className="eval-field ai-gen-count">
              <span className="eval-label">Cases</span>
              <input
                type="number" min={1} max={30} className="eval-count-input"
                value={count}
                onChange={(e) => setCount(Math.max(1, Math.min(30, parseInt(e.target.value) || 10)))}
              />
            </label>
          </div>
          <textarea
            className="eval-textarea" rows={2}
            placeholder="Focus (optional) — e.g. misspelled city names, multi-day forecasts, requests it should refuse"
            value={focus}
            onChange={(e) => setFocus(e.target.value)}
          />
          <div className="eval-form-actions">
            <button type="button" className="eval-save-btn" disabled={!appId || generating} onClick={generate}>
              {generating ? 'Generating…' : drafts.length ? '↻ Try again' : '✨ Generate'}
            </button>
            <span className="eval-label">
              Reads the pipeline and every sub-pipeline it calls (prompts, tools, models) and uses its own model.
              {targetId && mode !== 'regenerate' ? ' Cases already in the dataset are not repeated.' : ''}
            </span>
          </div>
          {error && <div className="eval-generate-msg eval-generate-msg--warn">⚠ {error}</div>}

          {result && (
            <div className="ai-gen-review">
              <div className="ai-gen-meta">
                {drafts.length} new case{drafts.length === 1 ? '' : 's'} from{' '}
                <strong>{result.pipeline.name}{result.pipeline.version ? ` v${result.pipeline.version}` : ' (draft)'}</strong>
                {result.pipeline.sub_pipelines.length > 0 && <> incl. {result.pipeline.sub_pipelines.join(', ')}</>}
                {' '}· {result.model_used}
                {result.skipped_duplicates > 0 && <> · {result.skipped_duplicates} duplicate{result.skipped_duplicates === 1 ? '' : 's'} dropped</>}
                {drafts.length > 0 && (
                  <>
                    {' '}·{' '}
                    <button type="button" className="link-btn" onClick={() => setDrafts((p) => p.map((c) => ({ ...c, keep: kept.length < p.length })))}>
                      {kept.length < drafts.length ? 'Select all' : 'Select none'}
                    </button>
                  </>
                )}
              </div>
              {result.pipeline.warnings.map((w) => <div key={w} className="eval-warn">⚠ {w}</div>)}

              <div className="ai-gen-list">
                {drafts.map((c, i) => (
                  <div key={i} className={`ai-gen-case${c.keep ? '' : ' ai-gen-case--off'}`}>
                    <input type="checkbox" checked={c.keep} onChange={(e) => updateDraft(i, { keep: e.target.checked })} />
                    <div className="ai-gen-case-body">
                      <textarea
                        className="eval-textarea" rows={2} value={c.prompt}
                        onChange={(e) => updateDraft(i, { prompt: e.target.value })}
                      />
                      <input
                        type="text" className="eval-input" placeholder="Expected output (optional)"
                        value={c.expected_output}
                        onChange={(e) => updateDraft(i, { expected_output: e.target.value })}
                      />
                      <div className="ai-gen-tags">
                        {c.tags.map((t) => <span key={t} className={`ai-gen-tag ai-gen-tag--${t}`}>{t.replace('_', ' ')}</span>)}
                      </div>
                    </div>
                    <button type="button" className="eval-del-btn" title="Discard" onClick={() => setDrafts((p) => p.filter((_, j) => j !== i))}>✕</button>
                  </div>
                ))}
              </div>

              <div className="ai-gen-row ai-gen-save">
                {!dataset && (
                  <label className="eval-field">
                    <span className="eval-label">Save to</span>
                    <select className="eval-select" value={target} onChange={(e) => setTarget(e.target.value)}>
                      <option value={NEW_DATASET}>New dataset…</option>
                      {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                    </select>
                  </label>
                )}
                {!targetId && (
                  <label className="eval-field">
                    <span className="eval-label">Dataset name</span>
                    <input type="text" className="eval-input" value={newName} onChange={(e) => setNewName(e.target.value)} />
                  </label>
                )}
                <button type="button" className="eval-save-btn" disabled={!kept.length || saving} onClick={save}>
                  {saving ? 'Saving…'
                    : mode === 'regenerate' ? `Replace AI cases with ${kept.length}`
                    : `${targetId ? 'Add' : 'Save'} ${kept.length} case${kept.length === 1 ? '' : 's'}`}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
