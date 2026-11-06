/**
 * Evaluate → Feedback: 👍 / 👎 from the people who read the answers (backend routers/feedback.py,
 * plan.md F2) — builders in the Prompt Runner, chat-link visitors, and API callers' end users.
 * The summary shows satisfaction per pipeline and version, so a new version that answers worse
 * shows up; the list shows each rated run's prompt, answer and note. Selected ratings become eval
 * cases: expected = the rater's correction, or the answer itself for a 👍.
 */
import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../../types'
import type { EvalDatasetRow } from './DatasetDetail'

type Source = '' | 'runner' | 'chat_link' | 'api'

export interface FeedbackItem {
  id: string
  app_id: string | null
  app_name: string | null
  app_version: number
  run_id: string
  source: Exclude<Source, ''>
  rater: string
  rating: 1 | -1
  comment: string
  correction: string
  prompt: string
  output: string
  dataset_id: string | null
  updated_at: string
}

export interface FeedbackSummaryRow {
  app_id: string | null
  app_name: string
  version: number
  up: number
  down: number
  total: number
  comments: number
  satisfaction: number | null
  last_at: string
}

const SOURCE_LABEL: Record<Exclude<Source, ''>, string> = { runner: 'Prompt Runner', chat_link: 'Chat link', api: 'API' }
const PAGE = 50

async function errorText(r: Response): Promise<string> {
  const d = await r.json().catch(() => ({}))
  return typeof d.detail === 'string' ? d.detail : r.statusText
}

const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

export function FeedbackPanel({ datasets, onExported }: { datasets: EvalDatasetRow[]; onExported?: () => void }) {
  const [summary, setSummary] = useState<FeedbackSummaryRow[]>([])
  const [items, setItems] = useState<FeedbackItem[]>([])
  const [total, setTotal] = useState(0)
  const [appId, setAppId] = useState('')
  const [rating, setRating] = useState<'' | '1' | '-1'>('-1')   // 👎 first: the ones to act on
  const [source, setSource] = useState<Source>('')
  const [days, setDays] = useState(30)
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<string | null>(null)
  const [datasetId, setDatasetId] = useState('')
  const [datasetName, setDatasetName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const q = new URLSearchParams({ days: String(days), limit: String(PAGE), offset: String(offset) })
    if (appId) q.set('app_id', appId)
    if (rating) q.set('rating', rating)
    if (source) q.set('source', source)
    try {
      const [s, l] = await Promise.all([
        fetch(`${API_BASE}/api/feedback/summary?days=${days}`),
        fetch(`${API_BASE}/api/feedback?${q}`),
      ])
      if (!s.ok || !l.ok) {
        setError(await errorText(s.ok ? l : s))
        return
      }
      setSummary(await s.json())
      const body: { total: number; items: FeedbackItem[] } = await l.json()
      setItems(body.items)
      setTotal(body.total)
    } catch {
      setError('Backend not reachable.')
    } finally {
      setLoading(false)
    }
  }, [appId, rating, source, days, offset])

  useEffect(() => { void load() }, [load])
  // A new filter starts at the first page with nothing selected
  const filter = <T,>(set: (v: T) => void) => (v: T) => { set(v); setOffset(0); setSelected(new Set()) }

  const toggle = (id: string) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const exportCases = async () => {
    setError('')
    setNotice('')
    const r = await fetch(`${API_BASE}/api/feedback/export`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feedback_ids: [...selected], dataset_id: datasetId, dataset_name: datasetName.trim() }),
    }).catch(() => null)
    if (!r) return setError('Backend not reachable.')
    if (!r.ok) return setError(await errorText(r))
    const out = await r.json()
    setNotice(`Added ${out.cases_created} case(s)` + (out.skipped_duplicates ? `, ${out.skipped_duplicates} already in the dataset` : '') + '.')
    setSelected(new Set())
    setDatasetName('')
    onExported?.()
    void load()
  }

  const pipelines = [...new Map(summary.filter((s) => s.app_id).map((s) => [s.app_id!, s.app_name || s.app_id!])).entries()]

  return (
    <div className="eval-tab-body">
      <div className="eval-toolbar">
        <select className="eval-input" aria-label="Pipeline" value={appId} onChange={(e) => filter(setAppId)(e.target.value)}>
          <option value="">All pipelines</option>
          {pipelines.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
        <select className="eval-input" aria-label="Rating" value={rating} onChange={(e) => filter(setRating)(e.target.value as typeof rating)}>
          <option value="-1">👎 only</option>
          <option value="1">👍 only</option>
          <option value="">👍 and 👎</option>
        </select>
        <select className="eval-input" aria-label="From" value={source} onChange={(e) => filter(setSource)(e.target.value as Source)}>
          <option value="">From anyone</option>
          {(Object.keys(SOURCE_LABEL) as Exclude<Source, ''>[]).map((s) => <option key={s} value={s}>{SOURCE_LABEL[s]}</option>)}
        </select>
        <select className="eval-input" aria-label="Period" value={days} onChange={(e) => filter(setDays)(Number(e.target.value))}>
          {[7, 30, 90, 0].map((d) => <option key={d} value={d}>{d ? `Last ${d} days` : 'All time'}</option>)}
        </select>
        <button type="button" className="eval-action-btn" onClick={load} disabled={loading}>↻</button>
      </div>

      {error && <div className="eval-warn" role="alert">{error}</div>}

      {summary.length > 0 && (
        <div className="fb-summary">
          {summary.filter((s) => !appId || s.app_id === appId).map((s) => (
            <div key={`${s.app_id}:${s.version}`} className="fb-summary-card">
              <span className="fb-summary-name">{s.app_name || s.app_id || 'Unsaved pipeline'} · v{s.version}</span>
              <span className={`fb-summary-rate${s.satisfaction !== null && s.satisfaction < 0.7 ? ' fb-summary-rate--low' : ''}`}>
                {pct(s.satisfaction)}
              </span>
              <span className="fb-summary-counts">👍 {s.up} · 👎 {s.down}{s.comments ? ` · ${s.comments} note(s)` : ''}</span>
            </div>
          ))}
        </div>
      )}

      {items.length === 0 && !loading && !error && (
        <div className="eval-empty">
          No ratings yet{rating ? ' with this rating' : ''}. Answers get 👍 / 👎 in the Prompt Runner, on chat links,
          and through <code>POST /v1/runs/&#123;run_id&#125;/feedback</code>.
        </div>
      )}

      <div className="fb-list">
        {items.map((f) => (
          <div key={f.id} className={`fb-item${f.rating < 0 ? ' fb-item--down' : ''}`}>
            <div className="fb-item-head">
              <input type="checkbox" aria-label="Select" checked={selected.has(f.id)} onChange={() => toggle(f.id)} />
              <span className="fb-item-rating">{f.rating > 0 ? '👍' : '👎'}</span>
              <button type="button" className="fb-item-prompt" onClick={() => setExpanded(expanded === f.id ? null : f.id)}
                title="Show the answer">
                {f.prompt || <em>(no prompt recorded)</em>}
              </button>
              <span className="fb-item-meta">
                {f.app_name || f.app_id} v{f.app_version} · {SOURCE_LABEL[f.source]} · {f.rater}
                {' · '}{new Date(f.updated_at + (f.updated_at.endsWith('Z') ? '' : 'Z')).toLocaleString()}
                {f.dataset_id && <span className="fb-item-exported" title="Already exported to an eval dataset"> · in evals</span>}
              </span>
            </div>
            {f.comment && <div className="fb-item-note">“{f.comment}”</div>}
            {expanded === f.id && (
              <div className="fb-item-body">
                <span className="eval-label">Answer</span>
                <pre className="fb-item-text">{f.output || '(no answer recorded)'}</pre>
                {f.correction && (<>
                  <span className="eval-label">Should have said</span>
                  <pre className="fb-item-text">{f.correction}</pre>
                </>)}
                <span className="fb-item-run">Run {f.run_id}</span>
              </div>
            )}
          </div>
        ))}
      </div>

      {total > PAGE && (
        <div className="eval-form-actions">
          <button type="button" className="eval-action-btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Newer</button>
          <span className="fb-item-meta">{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
          <button type="button" className="eval-action-btn" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Older →</button>
        </div>
      )}

      {items.length > 0 && (
        <div className="eval-form-card">
          <span className="eval-label">
            Turn {selected.size ? `${selected.size} selected rating(s)` : 'selected ratings'} into eval cases
          </span>
          <div className="eval-form-actions">
            <button type="button" className="eval-action-btn" onClick={() => setSelected(new Set(items.map((i) => i.id)))}>
              Select page
            </button>
            <select className="eval-input" aria-label="Dataset" value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
              <option value="">New dataset…</option>
              {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
            {!datasetId && (
              <input className="eval-input" placeholder="New dataset name" value={datasetName}
                onChange={(e) => setDatasetName(e.target.value)} />
            )}
            <button type="button" className="eval-save-btn" onClick={exportCases}
              disabled={!selected.size || (!datasetId && !datasetName.trim())}>Export</button>
          </div>
          {notice && <div className="eval-empty">{notice}</div>}
        </div>
      )}
    </div>
  )
}
