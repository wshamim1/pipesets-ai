import { useEffect, useMemo, useRef, useState } from 'react'
import { API_BASE } from '../../types'
import type { FlowNode, SyntheticDataColumn, SyntheticDataColumnType, SyntheticDataNodeData } from '../../types'
import { columnsToJsonSchema } from '../../utils/syntheticSchema'
import { inferColumnsFromCsv, parseCsvRecords } from '../../utils/syntheticCsv'
import { guessCaseColumns, rowHeaders, rowsToFile } from '../../utils/syntheticExport'
import { saveBlob } from '../../utils/download'

type Row = Record<string, unknown>
type Dataset = { id: string; name: string; case_count: number }

// Same limit as SYNTHETIC_MAX_ROWS in backend/routers/eval.py
const MAX_FULL_ROWS = 1000

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
  testLlm?: {
    provider?: string
    model?: string
    api_key?: string
    base_url?: string
    temperature?: number
    max_tokens?: number
    top_p?: number
  }
}

const COLUMN_TYPES: Array<{ value: SyntheticDataColumnType; label: string }> = [
  { value: 'string', label: 'String' },
  { value: 'integer', label: 'Integer' },
  { value: 'number', label: 'Number' },
  { value: 'boolean', label: 'Boolean' },
  { value: 'date', label: 'Date' },
  { value: 'datetime', label: 'DateTime' },
  { value: 'email', label: 'Email' },
  { value: 'uuid', label: 'UUID' },
  { value: 'category', label: 'Category' },
]

function makeColumn(): SyntheticDataColumn {
  return { id: `col-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, name: '', type: 'string', nullable: false, unique: false }
}

export function SyntheticDataConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly, testLlm }: Props) {
  const data = activeNode.data as SyntheticDataNodeData
  const columns = Array.isArray(data.columns) ? data.columns : []
  const set = (fields: Partial<SyntheticDataNodeData>) => onUpdate(activeNode.id, fields)
  const updateColumn = (id: string, patch: Partial<SyntheticDataColumn>) =>
    set({ columns: columns.map((c) => (c.id === id ? { ...c, ...patch } : c)) })
  const removeColumn = (id: string) => set({ columns: columns.filter((c) => c.id !== id) })
  const onSchemaModeChange = (mode: SyntheticDataNodeData['schema_mode']) => {
    if (mode === 'json' && !String(data.schema_json || '').trim()) {
      set({ schema_mode: mode, schema_json: columnsToJsonSchema(columns) })
      return
    }
    set({ schema_mode: mode })
  }
  const [testPrompt, setTestPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [previewRows, setPreviewRows] = useState<Array<Record<string, unknown>>>(Array.isArray(data.generated_preview_rows) ? data.generated_preview_rows : [])
  const [modelUsed, setModelUsed] = useState(String(data.generated_preview_model || ''))
  const [previewError, setPreviewError] = useState<string | null>(null)
  const csvInputRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    setPreviewRows(Array.isArray(data.generated_preview_rows) ? data.generated_preview_rows : [])
    setModelUsed(String(data.generated_preview_model || ''))
  }, [activeNode.id, data.generated_preview_rows, data.generated_preview_model])
  const headers = useMemo(() => rowHeaders(previewRows), [previewRows])

  // Full generation and its export / save. The rows stay in the panel, not in the saved flow.
  const [fullRows, setFullRows] = useState<Row[]>([])
  const [fullProgress, setFullProgress] = useState<{ rows: number; total: number } | null>(null)
  const [fullMsg, setFullMsg] = useState<{ text: string; warn?: boolean } | null>(null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [target, setTarget] = useState('new')
  // null = not picked yet: use the guess from the column names
  const [promptChoice, setPromptChoice] = useState<string | null>(null)
  const [expectedChoice, setExpectedChoice] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<{ text: string; warn?: boolean } | null>(null)
  const [fullNodeId, setFullNodeId] = useState(activeNode.id)
  if (fullNodeId !== activeNode.id) {        // another node opened in this panel: drop the last one's run
    setFullNodeId(activeNode.id)
    setFullRows([])
    setFullProgress(null)
    setFullMsg(null)
    setSaveMsg(null)
  }
  const exportRows = fullRows.length > 0 ? fullRows : previewRows
  const exportHeaders = useMemo(() => rowHeaders(exportRows), [exportRows])
  const guess = guessCaseColumns(exportHeaders)
  const picked = (choice: string | null, fallback: string) =>
    choice !== null && (choice === '' || exportHeaders.includes(choice)) ? choice : fallback
  const promptColumn = picked(promptChoice, guess.prompt)
  const expectedColumn = picked(expectedChoice, guess.expected)
  const loadDatasets = () =>
    fetch(`${API_BASE}/api/eval/datasets`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setDatasets)
      .catch(() => { /* the picker falls back to "New dataset" */ })
  useEffect(() => { if (!readOnly) loadDatasets() }, [readOnly])

  const generationSpec = (extra: Record<string, unknown>) => JSON.stringify({
    llm_config: testLlm,
    dataset_name: data.dataset_name,
    row_count: data.row_count,
    output_format: data.output_format,
    schema_mode: data.schema_mode,
    schema_json: data.schema_json,
    columns: data.columns,
    locale: data.locale,
    seed: data.seed,
    strict_schema: data.strict_schema,
    include_edge_cases: data.include_edge_cases,
    prompt_instructions: data.prompt_instructions,
    test_prompt: testPrompt,
    ...extra,
  })

  const generateAll = async () => {
    setFullMsg(null)
    setSaveMsg(null)
    setFullProgress({ rows: 0, total: data.row_count })
    try {
      const r = await fetch(`${API_BASE}/api/eval/synthetic-generate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: generationSpec({}),
      })
      if (!r.ok || !r.body) {
        const body = await r.json().catch(() => ({}))
        setFullMsg({ text: typeof body.detail === 'string' ? body.detail : r.statusText, warn: true })
        return
      }
      // NDJSON: progress lines, then one done / error line
      const reader = r.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let nl: number
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl).trim()
          buf = buf.slice(nl + 1)
          if (!line) continue
          const ev = JSON.parse(line)
          if (ev.type === 'progress') setFullProgress({ rows: ev.rows, total: ev.total })
          else if (ev.type === 'error') setFullMsg({ text: String(ev.detail), warn: true })
          else if (ev.type === 'done') {
            setFullRows(ev.rows)
            setModelUsed(String(ev.model_used || ''))
            const notes = [
              ev.dropped_rows ? `${ev.dropped_rows} invalid or duplicate row(s) replaced` : '',
              ev.failed_batches ? `${ev.failed_batches} batch(es) failed: ${ev.warning}` : '',
            ].filter(Boolean)
            setFullMsg({
              text: `Generated ${ev.generated} of ${ev.requested} rows.${notes.length ? ' ' + notes.join('; ') + '.' : ''}`,
              warn: ev.generated < ev.requested || ev.failed_batches > 0,
            })
          }
        }
      }
    } catch (e) {
      setFullMsg({ text: e instanceof Error ? e.message : String(e), warn: true })
    } finally {
      setFullProgress(null)
    }
  }

  const download = () => {
    const f = rowsToFile(exportRows, data.output_format, data.dataset_name)
    saveBlob(new Blob([f.content], { type: f.mime }), f.filename)
  }

  const saveToDataset = async () => {
    setSaving(true)
    setSaveMsg(null)
    try {
      const r = await fetch(`${API_BASE}/api/eval/synthetic-save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rows: exportRows,
          dataset_id: target === 'new' ? null : target,
          dataset_name: data.dataset_name,
          prompt_column: promptColumn,
          expected_column: expectedColumn,
        }),
      })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) {
        setSaveMsg({ text: typeof body.detail === 'string' ? body.detail : r.statusText, warn: true })
        return
      }
      const name = target === 'new' ? data.dataset_name : datasets.find((d) => d.id === target)?.name ?? 'dataset'
      const skipped = body.rows - body.cases_created
      setSaveMsg({ text: `Saved ${body.cases_created} case(s) to "${name}"${skipped ? ` — ${skipped} skipped (empty or already there)` : ''}. Open Evaluate to run it.` })
      await loadDatasets()
      setTarget(body.dataset_id)
    } catch (e) {
      setSaveMsg({ text: e instanceof Error ? e.message : String(e), warn: true })
    } finally {
      setSaving(false)
    }
  }

  const generatePreview = async () => {
    setGenerating(true)
    setPreviewError(null)
    try {
      const r = await fetch(`${API_BASE}/api/eval/synthetic-preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: generationSpec({ preview_rows: Math.max(1, Math.min(20, data.row_count)) }),
      })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) {
        setPreviewError(typeof body.detail === 'string' ? body.detail : r.statusText)
        return
      }
      setPreviewRows(Array.isArray(body.rows) ? body.rows : [])
      setModelUsed(String(body.model_used || ''))
      set({
        generated_preview_rows: Array.isArray(body.rows) ? body.rows : [],
        generated_preview_model: String(body.model_used || ''),
        generated_preview_at: new Date().toISOString(),
      })
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e))
    } finally {
      setGenerating(false)
    }
  }

  const onPickCsv = async (file?: File | null) => {
    if (!file) return
    setPreviewError(null)
    try {
      const text = await file.text()
      const records = parseCsvRecords(text)
      if (records.length === 0) {
        setPreviewError('CSV has no data rows (header + at least 1 row required).')
        return
      }
      const inferred = inferColumnsFromCsv(records)
      const schemaJson = columnsToJsonSchema(inferred)
      const preview = records.slice(0, 50)
      setPreviewRows(preview)
      setModelUsed('csv-upload')
      set({
        dataset_name: data.dataset_name || file.name.replace(/\.csv$/i, ''),
        schema_mode: 'manual',
        columns: inferred,
        schema_json: schemaJson,
        generated_preview_rows: preview,
        generated_preview_model: 'csv-upload',
        generated_preview_at: new Date().toISOString(),
      })
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e))
    } finally {
      if (csvInputRef.current) csvInputRef.current.value = ''
    }
  }

  return (
    <div className="bottom-config-grid synthetic-config-grid">
      <div className="config-card synthetic-card-basic">
        <h4 className="card-heading">1. Dataset Basics</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => set({ label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Dataset Name</label>
          <input type="text" className="field-input" value={data.dataset_name} disabled={readOnly}
            onChange={(e) => set({ dataset_name: e.target.value })} />
        </div>
        <div className="form-row">
          <div className="form-group flex-1">
            <label className="field-label">Rows</label>
            <input type="number" min="1" max="1000000" className="field-input" value={data.row_count} disabled={readOnly}
              onChange={(e) => set({ row_count: Math.max(1, parseInt(e.target.value, 10) || 100) })} />
          </div>
          <div className="form-group flex-1">
            <label className="field-label">Output Format</label>
            <select className="field-select" value={data.output_format} disabled={readOnly}
              onChange={(e) => set({ output_format: e.target.value as SyntheticDataNodeData['output_format'] })}>
              <option value="json">JSON</option>
              <option value="jsonl">JSONL</option>
              <option value="csv">CSV</option>
            </select>
          </div>
        </div>
      </div>

      <div className="config-card synthetic-card-controls">
        <h4 className="card-heading">2. Generation Controls</h4>
        <div className="form-row">
          <div className="form-group flex-1">
            <label className="field-label">Locale</label>
            <input type="text" className="field-input" value={data.locale} disabled={readOnly}
              onChange={(e) => set({ locale: e.target.value })} placeholder="en_US" />
          </div>
          <div className="form-group flex-1">
            <label className="field-label">Seed</label>
            <input type="number" className="field-input" value={data.seed} disabled={readOnly}
              onChange={(e) => set({ seed: parseInt(e.target.value, 10) || 42 })} />
          </div>
        </div>
        <div className="form-group">
          <label className="field-label">
            <input type="checkbox" checked={data.strict_schema} disabled={readOnly}
              onChange={(e) => set({ strict_schema: e.target.checked })} />
            {' '}Strict schema validation
          </label>
        </div>
        <div className="form-group">
          <label className="field-label">
            <input type="checkbox" checked={data.include_edge_cases} disabled={readOnly}
              onChange={(e) => set({ include_edge_cases: e.target.checked })} />
            {' '}Include edge-case records
          </label>
        </div>
        <div className="form-group">
          <label className="field-label">
            <input type="checkbox" checked={data.strict_routing === true} disabled={readOnly}
              onChange={(e) => set({ strict_routing: e.target.checked })} />
            {' '}Strict route to best matching dataset only
          </label>
        </div>
      </div>

      <div className="config-card synthetic-card-schema">
        <h4 className="card-heading">3. Schema</h4>
        <div className="form-group">
          <label className="field-label">Schema Mode</label>
          <select className="field-select" value={data.schema_mode} disabled={readOnly}
            onChange={(e) => onSchemaModeChange(e.target.value as SyntheticDataNodeData['schema_mode'])}>
            <option value="manual">Manual columns</option>
            <option value="json">JSON schema</option>
          </select>
        </div>

        {data.schema_mode === 'json' ? (
          <div className="form-group">
            <label className="field-label">JSON Schema</label>
            <textarea rows={10} className="field-textarea code-font" value={data.schema_json} disabled={readOnly}
              onChange={(e) => set({ schema_json: e.target.value })}
              placeholder={`{\n  "type": "object",\n  "properties": {\n    "customer_id": { "type": "string" }\n  }\n}`} />
          </div>
        ) : (
          <>
            <div className="tool-status-box">
              <span>{columns.length} column{columns.length === 1 ? '' : 's'} configured</span>
            </div>
            {columns.map((col) => (
              <div key={col.id} className="synthetic-column-card" style={{ marginTop: 10 }}>
                <div className="form-row">
                  <div className="form-group flex-1">
                    <label className="field-label">Column Name</label>
                    <input type="text" className="field-input" value={col.name} disabled={readOnly}
                      onChange={(e) => updateColumn(col.id, { name: e.target.value })} placeholder="customer_id" />
                  </div>
                  <div className="form-group flex-1">
                    <label className="field-label">Type</label>
                    <select className="field-select" value={col.type} disabled={readOnly}
                      onChange={(e) => updateColumn(col.id, { type: e.target.value as SyntheticDataColumnType })}>
                      {COLUMN_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                    </select>
                  </div>
                </div>
                <div className="form-row">
                  <label className="field-label">
                    <input type="checkbox" checked={col.nullable} disabled={readOnly}
                      onChange={(e) => updateColumn(col.id, { nullable: e.target.checked })} />
                    {' '}Nullable
                  </label>
                  <label className="field-label" style={{ marginLeft: 16 }}>
                    <input type="checkbox" checked={col.unique} disabled={readOnly}
                      onChange={(e) => updateColumn(col.id, { unique: e.target.checked })} />
                    {' '}Unique
                  </label>
                </div>
                {(col.type === 'number' || col.type === 'integer') && (
                  <div className="form-row">
                    <div className="form-group flex-1">
                      <label className="field-label">Min</label>
                      <input type="number" className="field-input" value={col.min ?? ''} disabled={readOnly}
                        onChange={(e) => updateColumn(col.id, { min: e.target.value === '' ? undefined : Number(e.target.value) })} />
                    </div>
                    <div className="form-group flex-1">
                      <label className="field-label">Max</label>
                      <input type="number" className="field-input" value={col.max ?? ''} disabled={readOnly}
                        onChange={(e) => updateColumn(col.id, { max: e.target.value === '' ? undefined : Number(e.target.value) })} />
                    </div>
                  </div>
                )}
                {col.type === 'category' && (
                  <div className="form-group">
                    <label className="field-label">Allowed values (comma-separated)</label>
                    <input type="text" className="field-input" value={col.values ?? ''} disabled={readOnly}
                      onChange={(e) => updateColumn(col.id, { values: e.target.value })} placeholder="gold, silver, bronze" />
                  </div>
                )}
                {!readOnly && (
                  <button type="button" className="delete-btn" onClick={() => removeColumn(col.id)}>Remove column</button>
                )}
              </div>
            ))}
            {!readOnly && (
              <button type="button" className="btn btn-secondary" style={{ marginTop: 10 }} onClick={() => set({ columns: [...columns, makeColumn()] })}>
                + Add column
              </button>
            )}
          </>
        )}
      </div>

      <div className="config-card synthetic-card-preview">
        <h4 className="card-heading">4. Prompting, Preview &amp; Actions</h4>
        <div className="form-group">
          <label className="field-label">Generation Instructions</label>
          <textarea rows={4} className="field-textarea" value={data.prompt_instructions} disabled={readOnly}
            onChange={(e) => set({ prompt_instructions: e.target.value })}
            placeholder="Describe realism constraints, distributions, and domain-specific rules." />
        </div>
        <div className="form-group">
          <label className="field-label">Prompt Override (optional)</label>
          <textarea rows={2} className="field-textarea" value={testPrompt} disabled={readOnly}
            onChange={(e) => setTestPrompt(e.target.value)}
            placeholder="Optional prompt to steer this generation." />
        </div>
        {!readOnly && (
          <div className="card-actions-row">
            <input
              ref={csvInputRef}
              type="file"
              accept=".csv,text/csv"
              style={{ display: 'none' }}
              onChange={(e) => onPickCsv(e.target.files?.[0] ?? null)}
            />
            <button type="button" className="btn btn-secondary" onClick={() => csvInputRef.current?.click()}>
              Upload CSV Sample
            </button>
            <button type="button" className="save-btn" onClick={generatePreview} disabled={generating}>
              {generating ? 'Generating…' : (previewRows.length > 0 ? 'Regenerate Preview' : 'Generate Preview')}
            </button>
            <button type="button" className="save-btn" onClick={onSave}>Save to App</button>
            <button type="button" className="delete-btn" onClick={() => onDelete(activeNode.id)}>Delete Node</button>
          </div>
        )}
        {data.generated_preview_at && (
          <div className="field-hint">Saved preview: {new Date(data.generated_preview_at).toLocaleString()}</div>
        )}
        {modelUsed && <div className="field-hint">Model: {modelUsed}</div>}
        {previewError && <div className="eval-generate-msg eval-generate-msg--warn">⚠ {previewError}</div>}
        {previewRows.length > 0 && (
          <div className="synthetic-preview-table-wrap">
            <table className="eval-table">
              <thead>
                <tr>{headers.map((h) => <th key={h}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {previewRows.map((row, idx) => (
                  <tr key={idx}>
                    {headers.map((h) => <td key={h}>{String(row[h] ?? '')}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {!readOnly && (
        <div className="config-card synthetic-card-full">
          <h4 className="card-heading">5. Full Dataset</h4>
          <div className="card-actions-row">
            <button type="button" className="save-btn" onClick={generateAll}
              disabled={fullProgress !== null || data.row_count > MAX_FULL_ROWS}>
              {fullProgress ? 'Generating…' : `Generate All ${data.row_count} Rows`}
            </button>
            <button type="button" className="btn btn-secondary" onClick={download} disabled={exportRows.length === 0}>
              Download {data.output_format.toUpperCase()}
            </button>
          </div>
          {data.row_count > MAX_FULL_ROWS && (
            <div className="field-hint">Full generation is limited to {MAX_FULL_ROWS} rows per run.</div>
          )}
          {fullProgress && (
            <div className="synthetic-progress">
              <progress max={fullProgress.total} value={fullProgress.rows} aria-label="Generation progress" />
              <span className="field-hint">{fullProgress.rows} / {fullProgress.total} rows</span>
            </div>
          )}
          {fullMsg && <div className={`eval-generate-msg${fullMsg.warn ? ' eval-generate-msg--warn' : ''}`}>{fullMsg.text}</div>}
          <div className="field-hint">
            {fullRows.length > 0
              ? `${fullRows.length} generated rows ready.`
              : previewRows.length > 0 ? `No full run yet — download and save use the ${previewRows.length} preview rows.` : 'Generate a preview or the full dataset first.'}
          </div>

          <h5 className="synthetic-subheading">Save to an eval dataset</h5>
          <div className="form-group">
            <label className="field-label" htmlFor="synthetic-target">Dataset</label>
            <select id="synthetic-target" className="field-select" value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="new">New dataset “{data.dataset_name || 'synthetic_dataset'}”</option>
              {datasets.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.case_count} cases)</option>)}
            </select>
          </div>
          <div className="form-row">
            <div className="form-group flex-1">
              <label className="field-label" htmlFor="synthetic-prompt-col">Prompt column</label>
              <select id="synthetic-prompt-col" className="field-select" value={promptColumn} onChange={(e) => setPromptChoice(e.target.value)}>
                <option value="">Whole row (as JSON)</option>
                {exportHeaders.map((h) => <option key={h} value={h}>{h}</option>)}
              </select>
            </div>
            <div className="form-group flex-1">
              <label className="field-label" htmlFor="synthetic-expected-col">Expected output column</label>
              <select id="synthetic-expected-col" className="field-select" value={expectedColumn} onChange={(e) => setExpectedChoice(e.target.value)}>
                <option value="">None</option>
                {exportHeaders.filter((h) => h !== promptColumn).map((h) => <option key={h} value={h}>{h}</option>)}
              </select>
            </div>
          </div>
          <div className="card-actions-row">
            <button type="button" className="save-btn" onClick={saveToDataset} disabled={saving || exportRows.length === 0}>
              {saving ? 'Saving…' : `Save ${exportRows.length} Row${exportRows.length === 1 ? '' : 's'} as Eval Cases`}
            </button>
          </div>
          {saveMsg && <div className={`eval-generate-msg${saveMsg.warn ? ' eval-generate-msg--warn' : ''}`}>{saveMsg.text}</div>}
        </div>
      )}
    </div>
  )
}
