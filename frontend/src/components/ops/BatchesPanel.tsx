/**
 * Automation → Batches: run a published pipeline once per row of a file (backend
 * routers/batches.py, plan.md F5). Upload a CSV / TSV / JSONL / JSON / Excel file (or one prompt per
 * line in a .txt), write a prompt template with {column} placeholders, and every row becomes one
 * background run — retried with backoff, resumable from its checkpoint, at most "rows at once" of
 * one batch running so schedules and webhooks keep their turn. Progress refreshes while a batch
 * runs; results download as CSV with the input columns plus output, status, cost and run id.
 */
import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../../types'
import type { AppRecord } from '../../types'
import { onDownload } from '../../utils/download'

type ItemStatus = 'pending' | 'queued' | 'running' | 'retrying' | 'completed' | 'failed' | 'paused' | 'cancelled'

export interface Batch {
  id: string
  app_id: string
  app_name: string
  name: string
  prompt_template: string
  columns: string[]
  source?: { kind: 'rows' | 'documents'; loader?: string; ocr_engine?: string }
  concurrency: number
  status: 'running' | 'done' | 'cancelled'
  total: number
  finished: number
  counts: Record<ItemStatus, number>
  cost_usd: number
  avg_latency_ms: number
  created_at: string
  finished_at: string | null
}

interface BatchItem {
  id: string
  idx: number
  prompt: string
  status: ItemStatus
  attempts: number
  run_id: string | null
  version: number
  output: string | null
  error: string | null
  latency_ms: number
  cost_usd: number
}

interface Parsed {
  columns: string[]
  rows: Record<string, unknown>[]
  total: number
  prompt_template: string
  filename: string
}

const STATUS_LABEL: Record<ItemStatus, string> = {
  pending: 'Waiting', queued: 'Queued', running: 'Running', retrying: 'Retrying', completed: 'Done',
  failed: 'Failed', paused: 'At a review gate', cancelled: 'Cancelled',
}
const POLL_MS = 3000
const ITEMS_PAGE = 100

async function errorText(r: Response): Promise<string> {
  if (r.status === 403) return 'You need write access to apps in this project to start or change batches.'
  const d = await r.json().catch(() => ({}))
  return typeof d.detail === 'string' ? d.detail : `HTTP ${r.status}`
}

/** The prompt a row makes — same rule as the backend (services/batches.render). */
function renderTemplate(template: string, row: Record<string, unknown>): string {
  return template.replace(/\{([^{}]+)\}/g, (_, name: string) => String(row[name.trim()] ?? '')).trim()
}

const fmt = (iso: string | null) => (iso ? new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleString() : '—')

function Progress({ batch }: { batch: Batch }) {
  const done = batch.counts.completed
  const bad = batch.counts.failed + batch.counts.cancelled + batch.counts.paused
  const w = (n: number) => `${batch.total ? (n / batch.total) * 100 : 0}%`
  return (
    <span className="batch-progress" title={`${done} done · ${bad} failed / cancelled · ${batch.total - batch.finished} to go`}>
      <span className="batch-progress-bar">
        <span className="batch-progress-ok" style={{ width: w(done) }} />
        <span className="batch-progress-bad" style={{ width: w(bad) }} />
      </span>
      <span className="batch-progress-text">{batch.finished} / {batch.total}</span>
    </span>
  )
}

const DOC_ACCEPT = '.pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.eml,.msg,.docx,.xlsx,.txt,.md,.csv,.json,.html'
const DOC_COLUMNS = ['document', 'filename', 'path']
const MAX_DOCUMENTS = 500

/** A pipeline that loads files itself (Structured Extract) gets the file's path; others its text. */
function documentTemplate(app: AppRecord | undefined): string {
  const extracts = (app?.flow_data?.nodes ?? []).some((n) => (n.data as { toolId?: string } | undefined)?.toolId === 'structured_extract')
  return extracts ? '{path}' : 'Summarise {filename}:\n\n{document}'
}

const fmtBytes = (n: number) => (n > 1024 * 1024 ? `${(n / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

function NewBatch({ apps, onCreated, onCancel }: { apps: AppRecord[]; onCreated: (b: Batch) => void; onCancel: () => void }) {
  const published = apps.filter((a) => a.version > 0)
  const [appId, setAppId] = useState(published[0]?.id ?? '')
  const [mode, setMode] = useState<'rows' | 'documents'>('rows')
  const [parsed, setParsed] = useState<Parsed | null>(null)
  const [docs, setDocs] = useState<File[]>([])
  const [loader, setLoader] = useState<'auto' | 'docling'>('auto')
  const [ocrEngine, setOcrEngine] = useState('auto')
  const [template, setTemplate] = useState('')
  const [name, setName] = useState('')
  const [concurrency, setConcurrency] = useState(2)
  const [retries, setRetries] = useState(2)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const app = published.find((a) => a.id === appId)

  const switchMode = (m: 'rows' | 'documents') => {
    setMode(m)
    setError('')
    setTemplate(m === 'documents' ? documentTemplate(app) : parsed?.prompt_template ?? '')
  }

  const upload = async (file: File) => {
    setError('')
    setParsed(null)
    const form = new FormData()
    form.append('file', file)
    const r = await fetch(`${API_BASE}/api/batches/parse`, { method: 'POST', body: form }).catch(() => null)
    if (!r) return setError('Backend not reachable.')
    if (!r.ok) return setError(await errorText(r))
    const body = await r.json()
    setParsed({ ...body, filename: file.name })
    setTemplate(body.prompt_template || body.columns.map((c: string) => `${c}: {${c}}`).join('\n'))
    if (!name) setName(file.name.replace(/\.[^.]+$/, ''))
  }

  const pickDocs = (files: File[]) => {
    setError(files.length > MAX_DOCUMENTS ? `A batch can have at most ${MAX_DOCUMENTS} documents` : '')
    setDocs(files)
    if (!template) setTemplate(documentTemplate(app))
    if (!name && files.length) setName(`${files.length} document${files.length === 1 ? '' : 's'}`)
  }

  // What the template can use, how many runs it makes, and what the first prompt looks like
  const columns = mode === 'documents' ? DOC_COLUMNS : parsed?.columns ?? []
  const count = mode === 'documents' ? docs.length : parsed?.total ?? 0
  const firstRow: Record<string, unknown> | null = mode === 'documents'
    ? (docs[0] ? { filename: docs[0].name, path: `…/${docs[0].name}`, document: `‹text of ${docs[0].name}›` } : null)
    : parsed?.rows[0] ?? null

  const unknown = [...template.matchAll(/\{([^{}]+)\}/g)].map((m) => m[1].trim()).filter((c) => !columns.includes(c))

  const start = async () => {
    setBusy(true)
    setError('')
    let r: Response | null
    if (mode === 'documents') {
      const form = new FormData()
      docs.forEach((f) => form.append('files', f, f.name))
      Object.entries({ app_id: appId, prompt_template: template, name, concurrency, retries, loader, ocr_engine: ocrEngine })
        .forEach(([k, v]) => form.append(k, String(v)))
      r = await fetch(`${API_BASE}/api/batches/documents`, { method: 'POST', body: form }).catch(() => null)
    } else {
      r = await fetch(`${API_BASE}/api/batches`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_id: appId, rows: parsed?.rows ?? [], prompt_template: template, name, concurrency, retries }),
      }).catch(() => null)
    }
    setBusy(false)
    if (!r) return setError('Backend not reachable.')
    if (!r.ok) return setError(await errorText(r))
    onCreated(await r.json())
  }

  const ready = mode === 'documents' ? docs.length > 0 && docs.length <= MAX_DOCUMENTS : !!parsed
  const unit = mode === 'documents' ? 'document' : 'row'

  return (
    <div className="batch-form">
      <div className="batch-form-row">
        <label className="batch-label" htmlFor="batch-app">Pipeline</label>
        <select id="batch-app" className="ops-select" value={appId} onChange={(e) => setAppId(e.target.value)}>
          {published.length === 0 && <option value="">No published pipelines</option>}
          {published.map((a) => <option key={a.id} value={a.id}>{a.name} (v{a.version})</option>)}
        </select>
      </div>
      <div className="batch-form-row">
        <span className="batch-label">Run over</span>
        <span className="batch-modes" role="radiogroup" aria-label="Run over">
          <button type="button" role="radio" aria-checked={mode === 'rows'} className={`batch-chip${mode === 'rows' ? ' batch-chip--on' : ''}`}
            onClick={() => switchMode('rows')}>Rows of a table</button>
          <button type="button" role="radio" aria-checked={mode === 'documents'} className={`batch-chip${mode === 'documents' ? ' batch-chip--on' : ''}`}
            onClick={() => switchMode('documents')}>Documents</button>
        </span>
      </div>
      {mode === 'rows' ? (
        <div className="batch-form-row">
          <label className="batch-label" htmlFor="batch-file">Rows</label>
          <input id="batch-file" type="file" accept=".csv,.tsv,.jsonl,.ndjson,.json,.xlsx,.txt"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f) }} />
          {parsed && <span className="batch-hint">{parsed.total} row(s) · columns: {parsed.columns.join(', ')}</span>}
        </div>
      ) : (<>
        <div className="batch-form-row">
          <label className="batch-label" htmlFor="batch-docs">Documents</label>
          <input id="batch-docs" type="file" multiple accept={DOC_ACCEPT}
            onChange={(e) => pickDocs(Array.from(e.target.files ?? []))} />
          {docs.length > 0 && (
            <span className="batch-hint">{docs.length} file(s) · {fmtBytes(docs.reduce((n, f) => n + f.size, 0))} — one run each</span>
          )}
        </div>
        <div className="batch-form-row">
          <label className="batch-label" htmlFor="batch-loader">Read with</label>
          <select id="batch-loader" className="ops-select" value={loader} onChange={(e) => setLoader(e.target.value as 'auto' | 'docling')}>
            <option value="auto">By file type (PDF, image OCR, email, Word, Excel, text)</option>
            <option value="docling">Docling for PDFs and scans (layout, tables)</option>
          </select>
          <label className="batch-label" htmlFor="batch-ocr">OCR</label>
          <select id="batch-ocr" className="ops-select" value={ocrEngine} onChange={(e) => setOcrEngine(e.target.value)}>
            <option value="auto">Auto (first installed)</option>
            <option value="tesseract">Tesseract</option>
            <option value="ocrmypdf">OCRmyPDF</option>
            <option value="docling">Docling</option>
            <option value="off">Off</option>
          </select>
        </div>
      </>)}
      {ready && (<>
        <div className="batch-form-row batch-form-row--top">
          <label className="batch-label" htmlFor="batch-template">Prompt</label>
          <div className="batch-template">
            <textarea id="batch-template" className="batch-textarea" rows={4} value={template}
              onChange={(e) => setTemplate(e.target.value)} />
            <div className="batch-chips">
              {columns.map((c) => (
                <button key={c} type="button" className="batch-chip" onClick={() => setTemplate((t) => `${t}{${c}}`)}>
                  {`{${c}}`}
                </button>
              ))}
            </div>
            {mode === 'documents' && (
              <span className="batch-hint">
                <code>{'{document}'}</code> is the file's text, read when its run starts. A Structured Extract pipeline
                loads the file itself — give it <code>{'{path}'}</code>; its fields go to Evaluate → Review under this batch's name.
              </span>
            )}
            {unknown.length > 0 && <div className="apikeys-error">No column named {unknown.join(', ')}</div>}
            <span className="batch-hint">First {unit}'s prompt:</span>
            <pre className="batch-preview">{renderTemplate(template, firstRow ?? {}) || '(empty)'}</pre>
          </div>
        </div>
        <div className="batch-form-row">
          <label className="batch-label" htmlFor="batch-name">Name</label>
          <input id="batch-name" className="batch-input" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
          <label className="batch-label" htmlFor="batch-conc" title="Rows of this batch running at the same time">Rows at once</label>
          <input id="batch-conc" className="batch-input batch-input--num" type="number" min={1} max={10} value={concurrency}
            onChange={(e) => setConcurrency(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} />
          <label className="batch-label" htmlFor="batch-retries">Retries</label>
          <input id="batch-retries" className="batch-input batch-input--num" type="number" min={0} max={10} value={retries}
            onChange={(e) => setRetries(Math.max(0, Math.min(10, Number(e.target.value) || 0)))} />
        </div>
      </>)}
      {error && <div className="apikeys-error" role="alert">{error}</div>}
      <div className="batch-form-actions">
        <button type="button" className="ops-refresh-btn" onClick={start}
          disabled={busy || !ready || !appId || unknown.length > 0 || !template.trim()}>
          {busy ? 'Starting…' : ready ? `Run ${count} ${unit}(s)` : 'Run'}
        </button>
        <button type="button" className="ops-link-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}

function BatchDetail({ batch, onChanged }: { batch: Batch; onChanged: () => void }) {
  const [status, setStatus] = useState<'' | ItemStatus>('')
  const [items, setItems] = useState<BatchItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    const q = new URLSearchParams({ offset: String(offset), limit: String(ITEMS_PAGE) })
    if (status) q.set('status', status)
    const r = await fetch(`${API_BASE}/api/batches/${batch.id}/items?${q}`).catch(() => null)
    if (!r || !r.ok) return
    const body = await r.json()
    setItems(body.items)
    setTotal(body.total)
  }, [batch.id, status, offset])

  // Reload rows whenever the batch's progress changes
  useEffect(() => { void load() }, [load, batch.finished, batch.status])

  const act = async (action: 'cancel' | 'retry' | 'delete') => {
    if (action === 'cancel' && !window.confirm('Cancel this batch? Rows not finished yet are stopped.')) return
    if (action === 'delete' && !window.confirm(`Delete “${batch.name}” and its results?`)) return
    setError('')
    const r = await fetch(`${API_BASE}/api/batches/${batch.id}${action === 'delete' ? '' : `/${action}`}`,
      { method: action === 'delete' ? 'DELETE' : 'POST' }).catch(() => null)
    if (!r) return setError('Backend not reachable.')
    if (!r.ok) return setError(await errorText(r))
    onChanged()
  }

  const retryable = batch.counts.failed + batch.counts.cancelled > 0
  return (
    <div className="batch-detail">
      <div className="batch-detail-head">
        <span className="batch-hint">
          {batch.app_name} · {batch.concurrency} at once · ${batch.cost_usd.toFixed(4)}
          {batch.avg_latency_ms ? ` · ${(batch.avg_latency_ms / 1000).toFixed(1)}s per row` : ''}
        </span>
        <span className="batch-actions">
          <button type="button" className="ops-refresh-btn" onClick={onDownload(`${API_BASE}/api/batches/${batch.id}/export`, `${batch.id}.csv`)}>
            ⬇ CSV
          </button>
          {batch.status === 'running' && <button type="button" className="ops-link-btn" onClick={() => act('cancel')}>Cancel</button>}
          {retryable && <button type="button" className="ops-refresh-btn" onClick={() => act('retry')}>Retry failed</button>}
          {batch.status !== 'running' && <button type="button" className="ops-link-btn" onClick={() => act('delete')}>Delete</button>}
        </span>
      </div>
      <pre className="batch-preview" title="Prompt template">{batch.prompt_template}</pre>
      {batch.source?.kind === 'documents' && (
        <span className="batch-hint">
          📄 One run per uploaded document. Structured Extract fields from these runs are in
          Evaluate → Review, batch “{batch.name}”.
        </span>
      )}
      {error && <div className="apikeys-error" role="alert">{error}</div>}
      <div className="batch-filter">
        {(['', 'completed', 'failed', 'running', 'pending', 'cancelled', 'paused'] as const).map((s) => (
          (s === '' || batch.counts[s] > 0) && (
            <button key={s} type="button" className={`batch-chip${status === s ? ' batch-chip--on' : ''}`} onClick={() => { setStatus(s); setOffset(0) }}>
              {s ? `${STATUS_LABEL[s]} ${batch.counts[s]}` : `All ${batch.total}`}
            </button>
          )
        ))}
      </div>
      <div className="batch-items">
        {items.map((it) => (
          <div key={it.id} className={`batch-item batch-item--${it.status}`}>
            <button type="button" className="batch-item-head" onClick={() => setOpen(open === it.id ? null : it.id)}>
              <span className="batch-item-idx">#{it.idx + 1}</span>
              <span className="batch-item-status">{STATUS_LABEL[it.status]}{it.attempts > 1 ? ` · ${it.attempts} tries` : ''}</span>
              <span className="batch-item-text">{it.error && it.status !== 'completed' ? it.error : it.output ?? it.prompt}</span>
              {it.cost_usd > 0 && <span className="batch-item-cost">${it.cost_usd.toFixed(4)}</span>}
            </button>
            {open === it.id && (
              <div className="batch-item-body">
                <span className="batch-hint">Prompt</span>
                <pre className="batch-preview">{it.prompt || '(empty)'}</pre>
                {it.output && (<><span className="batch-hint">Output</span><pre className="batch-preview">{it.output}</pre></>)}
                {it.error && (<><span className="batch-hint">Error</span><pre className="batch-preview">{it.error}</pre></>)}
                {it.run_id && <span className="batch-item-run">Run {it.run_id}{it.version ? ` · v${it.version}` : ''}</span>}
              </div>
            )}
          </div>
        ))}
      </div>
      {total > ITEMS_PAGE && (
        <div className="batch-form-actions">
          <button type="button" className="ops-link-btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - ITEMS_PAGE))}>← Previous</button>
          <span className="batch-hint">{offset + 1}–{Math.min(offset + ITEMS_PAGE, total)} of {total}</span>
          <button type="button" className="ops-link-btn" disabled={offset + ITEMS_PAGE >= total} onClick={() => setOffset(offset + ITEMS_PAGE)}>Next →</button>
        </div>
      )}
    </div>
  )
}

export function BatchesPanel({ apps }: { apps: AppRecord[] }) {
  const [list, setList] = useState<Batch[]>([])
  const [creating, setCreating] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const r = await fetch(`${API_BASE}/api/batches`)
      if (!r.ok) {
        setError(await errorText(r))
        return
      }
      setList(await r.json())
      setError('')
    } catch {
      setError('Backend not reachable.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  // Refresh while anything runs
  const running = list.some((b) => b.status === 'running')
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => { void load(true) }, POLL_MS)
    return () => clearInterval(t)
  }, [running, load])

  return (
    <div className="ops-panel">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">Batches</span>
        </div>
        <div className="ops-toolbar-right">
          {!creating && <button type="button" className="ops-refresh-btn" onClick={() => setCreating(true)}>+ New batch</button>}
          <button type="button" className="ops-refresh-btn" onClick={() => load()} disabled={loading}>
            {loading ? 'Loading…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      <div className="apikeys-body">
        <div className="apikeys-intro">
          Run a published pipeline once per row of a file — a folder of leases listed in a CSV, a set of support
          questions, an eval set against production. Each row is a background run with retries; open a row's run
          in <strong>Monitor → Traces</strong> by its id. Results download as CSV.
        </div>
        {error && <div className="apikeys-error" role="alert">{error}</div>}

        {creating && (
          <NewBatch apps={apps} onCancel={() => setCreating(false)}
            onCreated={(b) => { setCreating(false); setOpenId(b.id); void load(true) }} />
        )}

        <div className="ops-list">
          {list.length === 0 && !loading && !error && !creating && <div className="ops-empty">No batches yet.</div>}
          {list.map((b) => (
            <div key={b.id} className="batch-row">
              <button type="button" className="batch-row-head" onClick={() => setOpenId(openId === b.id ? null : b.id)}>
                <span className="batch-row-name">{b.name}</span>
                <span className={`batch-status batch-status--${b.status}`}>{b.status === 'done' ? 'Finished' : b.status === 'running' ? 'Running' : 'Cancelled'}</span>
                <Progress batch={b} />
                <span className="batch-row-date">{fmt(b.created_at)}</span>
              </button>
              {openId === b.id && <BatchDetail batch={b} onChanged={() => load(true)} />}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
