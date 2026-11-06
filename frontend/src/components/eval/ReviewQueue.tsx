/**
 * Evaluate → Review: fields extracted by the Structured Extract tool, waiting for a person
 * (services/extraction_reviews.py). Each shows the value, the page and the exact quote it came from,
 * and whether that quote was found on the page; "Page" opens the cited page with the quote marked.
 * Values other parts of a long document found are listed under it ("parts disagree" when one has a
 * found quote too). Approve, correct or reject per field, or bulk-approve fields with a found quote
 * above a confidence threshold. "Accuracy" shows approved vs corrected per field, by model and
 * prompt version. Reviewed documents can be exported to an eval dataset so corrections become test cases.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { API_BASE } from '../../types'
import { HelpLink } from '../docs/HelpLink'

export type ReviewStatus = 'pending' | 'approved' | 'corrected' | 'rejected'

export interface ReviewAlternative {
  value: unknown
  page: number | null
  page_label: string | null
  quote: string | null
  verified: boolean
  confidence: number
}

export interface ReviewItem {
  id: string
  batch: string
  source: string
  field: string
  description: string
  field_type: string
  value: unknown
  page: number | null
  page_label: string | null
  quote: string | null
  confidence: number
  verified: boolean
  status: ReviewStatus
  final_value: unknown
  note: string
  model: string
  reviewed_by: string | null
  reviewed_at: string | null
  created_at: string
  prompt_version: string
  alternatives: ReviewAlternative[]
  conflict: boolean
  bulk: boolean
}

interface ReviewPage { page: number; page_label: string | null; text: string | null }

interface AccuracyCounts {
  right: number; wrong: number; bulk: number; pending: number; checked: number; accuracy: number | null
  approved: number; corrected: number; rejected: number
}
interface AccuracyGroup extends AccuracyCounts {
  model: string
  prompt_version: string
  fields: (AccuracyCounts & { field: string })[]
}

const STATUSES: ReviewStatus[] = ['pending', 'approved', 'corrected', 'rejected']
const STATUS_LABEL: Record<ReviewStatus, string> = {
  pending: 'To review', approved: 'Approved', corrected: 'Corrected', rejected: 'Rejected',
}

async function errorText(r: Response): Promise<string> {
  const d = await r.json().catch(() => ({}))
  return typeof d.detail === 'string' ? d.detail : r.statusText
}

const show = (v: unknown) => (v === null || v === undefined ? '—' : typeof v === 'string' ? v : JSON.stringify(v))

/** A corrected value typed as the field's type, so numbers and booleans stay JSON numbers / booleans. */
export function typedValue(text: string, fieldType: string): unknown {
  const t = text.trim()
  if (['number', 'money', 'integer'].includes(fieldType)) {
    const n = Number(t.replace(/[$,\s]/g, ''))
    if (t !== '' && Number.isFinite(n)) return n
  }
  if (fieldType === 'boolean' && /^(true|false)$/i.test(t)) return t.toLowerCase() === 'true'
  return t
}

/** Splits ``text`` around ``quote`` (case, whitespace and punctuation aside) → [before, quote, after], or null. */
export function findQuote(text: string, quote: string | null): [string, string, string] | null {
  const words = (quote ?? '').split(/[^\p{L}\p{N}]+/u).filter(Boolean)
  if (!words.length) return null
  const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const m = new RegExp(escaped.join('[^\\p{L}\\p{N}]+'), 'iu').exec(text)
  return m ? [text.slice(0, m.index), m[0], text.slice(m.index + m[0].length)] : null
}

const pct = (n: number | null) => (n === null ? '—' : `${Math.round(n * 100)}%`)

function PageView({ item, page, onClose }: { item: ReviewItem; page: number | null; onClose: () => void }) {
  const [data, setData] = useState<ReviewPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const quote = page === item.page ? item.quote : item.alternatives.find((a) => a.page === page)?.quote ?? null

  useEffect(() => {
    const q = page !== null && page !== item.page ? `?page=${page}` : ''
    fetch(`${API_BASE}/api/reviews/${item.id}/page${q}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error(await errorText(r)))))
      .then((d: ReviewPage) => { setData(d); setError(null) })
      .catch((e) => setError(`Couldn't load the page: ${e.message}`))
  }, [item.id, item.page, page])

  const parts = data?.text ? findQuote(data.text, quote) : null
  return (
    <div className="review-page" data-testid={`review-page-${item.field}`}>
      <div className="review-page-head">
        <span>{data?.page_label ?? `Page ${page}`}</span>
        <button type="button" className="eval-action-btn" onClick={onClose} aria-label="Close page">×</button>
      </div>
      {error && <div className="eval-warn">{error}</div>}
      {data && data.text === null && <div className="eval-empty">This page wasn't kept (filed before pages were saved).</div>}
      {data?.text && (
        <div className="review-page-text">
          {parts ? <>{parts[0]}<mark>{parts[1]}</mark>{parts[2]}</> : data.text}
        </div>
      )}
      {data?.text && quote && !parts && <div className="review-was">The quote isn't on this page.</div>}
    </div>
  )
}

function ReviewRow({ item, onDecide }: {
  item: ReviewItem
  onDecide: (item: ReviewItem, decision: 'approve' | 'correct' | 'reject', value?: unknown) => Promise<boolean>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [openPage, setOpenPage] = useState<number | null>(null)
  const where = item.page_label ?? (item.page ? `page ${item.page}` : null)
  const togglePage = (no: number | null) => setOpenPage(openPage === no ? null : no)
  const decided = item.status !== 'pending'

  return (
    <div className={`review-row review-row--${item.status}`} data-testid={`review-${item.field}`}>
      <div className="review-row-head">
        <span className="review-field" title={item.description}>{item.field.replace(/_/g, ' ')}</span>
        {item.value === null
          ? <span className="review-badge review-badge--missing">not found</span>
          : item.verified
            ? <span className="review-badge review-badge--ok" title="The quote was found on the cited page">✓ quote found</span>
            : <span className="review-badge review-badge--warn" title="The quote isn't on the cited page — check the document">quote not found</span>}
        {item.conflict && (
          <span className="review-badge review-badge--warn" title="Another part of the document states a different value, with a quote found too">
            parts disagree
          </span>
        )}
        {item.bulk && <span className="review-badge review-badge--missing" title="Approved in bulk, not looked at one by one">bulk</span>}
        <span className="review-confidence">{Math.round(item.confidence * 100)}%</span>
      </div>
      <div className="review-value">{show(decided ? item.final_value : item.value)}</div>
      {item.status === 'corrected' && <div className="review-was">model said: {show(item.value)}</div>}
      {item.quote && (
        <blockquote className="review-quote">
          “{item.quote}”{where && <span className="review-where"> — {where}</span>}
        </blockquote>
      )}
      {item.alternatives.length > 0 && (
        <div className="review-alts">
          <span className="review-where">Other parts of the document found:</span>
          {item.alternatives.map((a, i) => (
            <div key={i} className="review-alt" data-testid={`review-alt-${item.field}-${i}`}>
              <span className="review-value">{show(a.value)}</span>
              <span className="review-where">
                {a.page_label ?? (a.page ? `page ${a.page}` : '')}{a.verified ? ' · ✓ quote found' : ' · quote not found'}
              </span>
              {a.quote && <blockquote className="review-quote">“{a.quote}”</blockquote>}
              <div className="eval-form-actions">
                <button type="button" className="eval-action-btn" onClick={() => onDecide(item, 'correct', a.value)}>
                  Use this value
                </button>
                {a.page !== null && (
                  <button type="button" className="eval-action-btn" onClick={() => togglePage(a.page)}>📄 Page {a.page}</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      {editing ? (
        <div className="eval-form-actions">
          <input
            className="eval-input"
            aria-label={`Correct ${item.field}`}
            value={draft}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
          />
          <button
            type="button"
            className="eval-save-btn"
            disabled={!draft.trim()}
            onClick={async () => { if (await onDecide(item, 'correct', typedValue(draft, item.field_type))) setEditing(false) }}
          >Save</button>
          <button type="button" className="eval-cancel-btn" onClick={() => setEditing(false)}>Cancel</button>
        </div>
      ) : (
        <div className="eval-form-actions">
          {item.value !== null && item.status !== 'approved' && (
            <button type="button" className="eval-action-btn eval-action-btn--primary" onClick={() => onDecide(item, 'approve')}>
              Approve
            </button>
          )}
          <button
            type="button"
            className="eval-action-btn"
            onClick={() => { setDraft(item.value === null ? '' : show(decided ? item.final_value : item.value)); setEditing(true) }}
          >Correct</button>
          {item.status !== 'rejected' && (
            <button type="button" className="eval-action-btn" onClick={() => onDecide(item, 'reject')}>Reject</button>
          )}
          {item.page !== null && (
            <button type="button" className="eval-action-btn" onClick={() => togglePage(item.page)}>📄 Page</button>
          )}
          {decided && item.reviewed_by && <span className="review-who">{STATUS_LABEL[item.status]} by {item.reviewed_by}</span>}
        </div>
      )}
      {openPage !== null && <PageView item={item} page={openPage} onClose={() => setOpenPage(null)} />}
    </div>
  )
}

function AccuracyReport({ batch }: { batch: string }) {
  const [groups, setGroups] = useState<AccuracyGroup[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const q = batch.trim() ? `?${new URLSearchParams({ batch: batch.trim() })}` : ''
    fetch(`${API_BASE}/api/reviews/report${q}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error(await errorText(r)))))
      .then((d: { groups: AccuracyGroup[] }) => { setGroups(d.groups); setError(null) })
      .catch((e) => setError(`Failed to load the report: ${e.message}`))
  }, [batch])

  if (error) return <div className="eval-warn">{error}</div>
  if (!groups) return null
  if (!groups.length) return <div className="eval-empty">No reviewed fields yet.</div>
  return (
    <div className="review-report">
      <div className="review-where">
        Right = approved, or rejected when the model said “not found”. Wrong = corrected, or rejected when it gave a value.
        Bulk approvals aren’t scored.
      </div>
      {groups.map((g) => (
        <div key={`${g.model} ${g.prompt_version}`} className="review-doc" data-testid={`report-${g.prompt_version}`}>
          <div className="review-doc-title" title={`${g.model} · prompt ${g.prompt_version || 'unknown'}`}>
            {g.model || 'unknown model'} · {g.prompt_version || 'prompt unknown'} — {pct(g.accuracy)} of {g.checked} checked
          </div>
          <table className="review-report-table">
            <thead>
              <tr><th>Field</th><th>Accuracy</th><th>Right</th><th>Wrong</th><th>Bulk</th><th>To review</th></tr>
            </thead>
            <tbody>
              {g.fields.map((f) => (
                <tr key={f.field}>
                  <td>{f.field.replace(/_/g, ' ')}</td>
                  <td>{pct(f.accuracy)}</td><td>{f.right}</td><td>{f.wrong}</td><td>{f.bulk}</td><td>{f.pending}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

export function ReviewQueue({ onExported }: { onExported?: () => void }) {
  const [status, setStatus] = useState<ReviewStatus>('pending')
  const [batch, setBatch] = useState('')
  const [items, setItems] = useState<ReviewItem[]>([])
  const [counts, setCounts] = useState<Record<ReviewStatus, number>>({ pending: 0, approved: 0, corrected: 0, rejected: 0 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [datasetName, setDatasetName] = useState('Reviewed extractions')
  const [exported, setExported] = useState<string | null>(null)
  const [view, setView] = useState<'queue' | 'report'>('queue')
  const [threshold, setThreshold] = useState(90)
  const [bulkMatching, setBulkMatching] = useState<number | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    const q = new URLSearchParams({ status })
    if (batch.trim()) q.set('batch', batch.trim())
    fetch(`${API_BASE}/api/reviews?${q}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error(await errorText(r)))))
      .then((d: { items: ReviewItem[]; counts: Record<ReviewStatus, number> }) => {
        setItems(d.items); setCounts(d.counts); setError(null)
      })
      .catch((e) => setError(`Failed to load the review queue: ${e.message}`))
      .finally(() => setLoading(false))
  }, [status, batch])

  useEffect(() => { load() }, [load])

  const bulkQuery = useMemo(() => {
    const q = new URLSearchParams({ min_confidence: String(threshold / 100) })
    if (batch.trim()) q.set('batch', batch.trim())
    return q
  }, [threshold, batch])

  const thresholdOk = threshold >= 50 && threshold <= 100

  useEffect(() => {
    if (status !== 'pending' || !thresholdOk) return
    fetch(`${API_BASE}/api/reviews/bulk-approve?${bulkQuery}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.statusText))))
      .then((d: { matching: number }) => setBulkMatching(d.matching))
      .catch(() => setBulkMatching(null))
  }, [status, bulkQuery, items, thresholdOk])
  const bulkCount = thresholdOk ? bulkMatching : null

  const bulkApprove = async () => {
    const r = await fetch(`${API_BASE}/api/reviews/bulk-approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ min_confidence: threshold / 100, batch: batch.trim() }),
    })
    if (!r.ok) { setError(await errorText(r)); return }
    setError(null)
    load()
  }

  const decide = async (item: ReviewItem, decision: 'approve' | 'correct' | 'reject', value?: unknown) => {
    const r = await fetch(`${API_BASE}/api/reviews/${item.id}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, value }),
    })
    if (!r.ok) { setError(await errorText(r)); return false }
    setError(null)
    load()
    return true
  }

  const exportCases = async () => {
    const r = await fetch(`${API_BASE}/api/reviews/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_name: datasetName.trim(), batch: batch.trim() }),
    })
    if (!r.ok) { setError(await errorText(r)); setExported(null); return }
    const d = await r.json()
    setError(null)
    setExported(`${d.cases_created} new case${d.cases_created === 1 ? '' : 's'} added (${d.skipped_duplicates} already there).`)
    onExported?.()
  }

  const bySource = useMemo(() => {
    const groups = new Map<string, ReviewItem[]>()
    for (const it of items) groups.set(it.source, [...(groups.get(it.source) ?? []), it])
    return [...groups.entries()]
  }, [items])

  return (
    <div className="eval-tab-body">
      <div className="eval-toolbar">
        <HelpLink page="12-document-extraction" section="5-review-queue" label="How to review extracted fields" />
        {STATUSES.map((s) => (
          <button
            key={s}
            type="button"
            className={`eval-action-btn${view === 'queue' && status === s ? ' eval-action-btn--primary' : ''}`}
            onClick={() => { setStatus(s); setView('queue') }}
          >{STATUS_LABEL[s]} ({counts[s]})</button>
        ))}
        <button
          type="button"
          className={`eval-action-btn${view === 'report' ? ' eval-action-btn--primary' : ''}`}
          onClick={() => setView('report')}
        >Accuracy</button>
        <button type="button" className="eval-action-btn" onClick={load} disabled={loading}>↻</button>
      </div>
      <input
        className="eval-input"
        placeholder="Batch (optional)"
        aria-label="Batch"
        value={batch}
        onChange={(e) => setBatch(e.target.value)}
      />
      {error && <div className="eval-warn">{error}</div>}

      {view === 'report' && <AccuracyReport batch={batch} />}
      {view === 'queue' && status === 'pending' && (
        <div className="eval-form-actions review-bulk">
          <label className="review-where" htmlFor="review-threshold">Bulk approve fields with a found quote at</label>
          <input
            id="review-threshold"
            className="eval-input review-threshold"
            type="number"
            min={50}
            max={100}
            step={5}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
          />
          <span className="review-where">% or more</span>
          <button
            type="button"
            className="eval-action-btn eval-action-btn--primary"
            disabled={!bulkCount}
            onClick={bulkApprove}
          >Approve {bulkCount ?? 0} field{bulkCount === 1 ? '' : 's'}</button>
        </div>
      )}

      {view === 'queue' && !loading && items.length === 0 && (
        <div className="eval-empty">
          {status === 'pending'
            ? 'Nothing to review. Fields extracted by the Structured Extract tool appear here.'
            : `No ${STATUS_LABEL[status].toLowerCase()} fields.`}
        </div>
      )}
      {view === 'queue' && bySource.map(([source, rows]) => (
        <div key={source} className="review-doc">
          <div className="review-doc-title" title={source}>📄 {source.split('/').pop()}</div>
          {rows.map((it) => <ReviewRow key={it.id} item={it} onDecide={decide} />)}
        </div>
      ))}

      <div className="eval-form-card">
        <span className="eval-label">Export reviewed documents to an eval dataset</span>
        <div className="eval-form-actions">
          <input
            className="eval-input"
            aria-label="Dataset name"
            value={datasetName}
            onChange={(e) => setDatasetName(e.target.value)}
          />
          <button type="button" className="eval-save-btn" disabled={!datasetName.trim()} onClick={exportCases}>Export</button>
        </div>
        {exported && <div className="eval-empty">{exported}</div>}
      </div>
    </div>
  )
}
