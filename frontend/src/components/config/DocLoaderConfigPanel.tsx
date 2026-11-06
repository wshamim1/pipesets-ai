import { useState, useRef } from 'react'
import type { Node } from '@xyflow/react'
import type { DocLoaderNodeData, ConnectionNodeData, FlowNode, FlowEdge } from '../../types'
import { DB_LOADER_TYPES, getDocLoader, useDocLoaders } from '../../utils/docLoaders'
import { API_BASE } from '../../types'
import { ConnectionIcon } from '../ConnectionIcon'
import { HelpLink } from '../docs/HelpLink'

// Loaders that can meet scanned pages or images, so the OCR settings apply
const OCR_LOADER_TYPES = new Set(['pdf', 'image', 'directory', 's3', 'email'])
const OCR_ENGINES: [NonNullable<DocLoaderNodeData['ocr_engine']>, string][] = [
  ['auto', 'Auto — first installed: OCRmyPDF, Tesseract, Docling'],
  ['tesseract', 'Tesseract (local)'],
  ['ocrmypdf', 'OCRmyPDF (local, PDFs; fixes rotation)'],
  ['docling', 'Docling (local; best on tables)'],
  ['vision', 'Vision model (cloud, billed per page)'],
  ['off', 'Off'],
]

interface Props {
  activeNode: FlowNode
  nodes: FlowNode[]
  edges: FlowEdge[]
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

export function DocLoaderConfigPanel({ activeNode, nodes, edges, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as DocLoaderNodeData
  const [inputMode, setInputMode] = useState<'upload' | 'path'>('upload')
  const [uploading, setUploading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState<string | null>(null)
  const [uploadedFiles, setUploadedFiles] = useState<string[]>([])
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setUploading(true)
    setUploadStatus('Uploading and processing…')

    try {
      const formData = new FormData()
      Array.from(files).forEach((f) => formData.append('files', f))

      const res = await fetch(`${API_BASE}/api/retrieval/upload`, {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) {
        const errText = await res.text()
        throw new Error(errText || 'Upload failed')
      }

      const json = await res.json()
      const primaryPath = json.primary_path || ''
      const names = json.file_names || []

      onUpdate(activeNode.id, { source: primaryPath })
      setUploadedFiles(names)
      setUploadStatus(`✓ Uploaded ${json.count} file(s)`)
    } catch (e: any) {
      setUploadStatus(`✕ Error: ${e.message}`)
    } finally {
      setUploading(false)
    }
  }

  const allDocLoaders = useDocLoaders()
  const customDocLoaders = allDocLoaders.filter((d) => d.custom)
  // Built-in loaders grouped by category, in catalog order
  const builtInGroups = allDocLoaders.filter((d) => !d.custom).reduce<Record<string, typeof allDocLoaders[number][]>>((acc, d) => {
    (acc[d.category || 'Other'] ??= []).push(d)
    return acc
  }, {})
  const loaderDef = getDocLoader(data.loader_type)
  const isFileBased = !!loaderDef?.fileBased
  const isCustom = !!loaderDef?.custom || data.loader_type.startsWith('custom_')
  const isDbBacked = DB_LOADER_TYPES.has(data.loader_type)

  // Resolve the connection node linked to this doc loader via an edge (if any)
  const linkedConnNode: Node<ConnectionNodeData, 'connection'> | undefined = (() => {
    const linkedIds = edges
      .filter((e) => e.source === activeNode.id || e.target === activeNode.id)
      .map((e) => (e.source === activeNode.id ? e.target : e.source))
    return nodes.find(
      (n) => n.type === 'connection' && linkedIds.includes(n.id),
    ) as Node<ConnectionNodeData, 'connection'> | undefined
  })()

  return (
    <div className="bottom-config-grid">
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Loader Type</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Loader Type</label>
          <select className="field-select" value={data.loader_type} disabled={readOnly}
            onChange={(e) => {
              const next = getDocLoader(e.target.value)
              onUpdate(activeNode.id, {
                loader_type: e.target.value as DocLoaderNodeData['loader_type'],
                loader_class: next?.custom ? next.loaderClass : undefined,
                loader_kwargs: next?.custom ? next.loaderKwargs : undefined,
              })
            }}>
            {!loaderDef && <option value={data.loader_type}>{data.loader_type}</option>}
            {customDocLoaders.length > 0 && (
              <optgroup label="Custom">
                {customDocLoaders.map((d) => (
                  <option key={d.type} value={d.type}>{d.label} — {d.desc}</option>
                ))}
              </optgroup>
            )}
            {Object.entries(builtInGroups).map(([category, list]) => (
              <optgroup key={category} label={category}>
                {list.map((d) => (
                  <option key={d.type} value={d.type} disabled={d.available === false && d.type !== data.loader_type}>
                    {d.label}{d.available === false ? ' (coming soon)' : ''} — {d.desc}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        {isCustom && (
          <>
            <div className="form-group">
              <label className="field-label">Loader Class / Import Path</label>
              <input type="text" className="field-input code-font" placeholder="my_package.loaders.MyLoader"
                value={data.loader_class ?? ''} disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { loader_class: e.target.value })} />
            </div>
            <div className="form-group">
              <label className="field-label">Constructor Kwargs (JSON)</label>
              <textarea rows={2} className="field-textarea code-font" style={{ fontSize: 11 }}
                placeholder='{ "encoding": "utf-8" }'
                value={data.loader_kwargs ?? ''} disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { loader_kwargs: e.target.value })} />
            </div>
          </>
        )}
      </div>

      <div className="config-card">
        <h4 className="card-heading">
          2. Source Document
          {isFileBased && (
            <span style={{ float: 'right', display: 'inline-flex', gap: 4 }}>
              <button
                type="button"
                className={`tab-btn ${inputMode === 'upload' ? 'active' : ''}`}
                style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, cursor: 'pointer', border: '1px solid #d1d5db', background: inputMode === 'upload' ? '#2563eb' : '#fff', color: inputMode === 'upload' ? '#fff' : '#374151' }}
                onClick={() => setInputMode('upload')}
              >
                📁 Upload
              </button>
              <button
                type="button"
                className={`tab-btn ${inputMode === 'path' ? 'active' : ''}`}
                style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, cursor: 'pointer', border: '1px solid #d1d5db', background: inputMode === 'path' ? '#2563eb' : '#fff', color: inputMode === 'path' ? '#fff' : '#374151' }}
                onClick={() => setInputMode('path')}
              >
                🔗 File Path
              </button>
            </span>
          )}
        </h4>

        {isDbBacked ? (
          <>
          {/* ── DB-backed loaders: link a Connection node instead of pasting a DSN ── */}
          {linkedConnNode ? (
            <div className="form-group">
              <div
                style={{
                  border: '1px solid #bbf7d0',
                  borderRadius: 8,
                  padding: '10px 12px',
                  background: '#f0fdf4',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 10,
                }}
              >
                <ConnectionIcon type={linkedConnNode.data.connection_type} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#15803d' }}>
                    {linkedConnNode.data.label}
                  </div>
                  <div style={{ fontSize: 11, color: '#374151', marginTop: 2 }}>
                    {linkedConnNode.data.connection_type.toUpperCase()} •{' '}
                    {linkedConnNode.data.config?.host ?? linkedConnNode.data.description}
                    {linkedConnNode.data.config?.database ? ` / ${linkedConnNode.data.config.database}` : ''}
                  </div>
                  <div
                    style={{
                      marginTop: 4,
                      fontSize: 10,
                      fontWeight: 600,
                      color: linkedConnNode.data.status === 'connected' ? '#15803d' : '#b91c1c',
                    }}
                  >
                    {linkedConnNode.data.status === 'connected' ? '🟢 Connected' : '🔴 ' + (linkedConnNode.data.status_msg?.slice(0, 50) ?? 'Error')}
                  </div>
                </div>
                <span style={{ fontSize: 10, color: '#6b7280', whiteSpace: 'nowrap', alignSelf: 'center' }}>
                  ✓ Linked
                </span>
              </div>
              <span className="field-hint" style={{ marginTop: 6, display: 'block' }}>
                Connection credentials come from the linked node. Draw a new edge to a different Connection node to switch.
              </span>
            </div>
          ) : (
            <div className="form-group">
              <div
                style={{
                  border: '2px dashed #f97316',
                  borderRadius: 8,
                  padding: '14px 16px',
                  background: '#fff7ed',
                  textAlign: 'center',
                  marginBottom: 10,
                }}
              >
                <span style={{ fontSize: 22 }}>🔗</span>
                <p style={{ margin: '6px 0 4px', fontSize: 12, fontWeight: 700, color: '#9a3412' }}>
                  No Connection linked
                </p>
                <p style={{ margin: 0, fontSize: 11, color: '#7c2d12' }}>
                  Drag a <strong>Connection node</strong> (e.g. Postgres, MySQL, MongoDB) from the sidebar onto the canvas and link it to this loader, or provide a direct URI below.
                </p>
              </div>
              <label className="field-label">Direct Connection URI (Fallback)</label>
              <input type="text" className="field-input code-font"
                placeholder="postgresql://labuser:labpass@localhost:5433/labdb"
                value={data.source} disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { source: e.target.value })} />
            </div>
          )}

          <div className="form-group" style={{ marginTop: 10 }}>
            <label className="field-label">Target Table (Optional)</label>
            <input type="text" className="field-input code-font"
              placeholder="e.g. customers (leave blank for all tables)"
              value={data.db_table ?? ''} disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { db_table: e.target.value })} />
            <span className="field-hint">Specify a single table or leave empty to auto-discover and ingest all public tables.</span>
          </div>

          <div className="form-group" style={{ marginTop: 10 }}>
            <label className="field-label">Custom SQL Query (Optional)</label>
            <textarea rows={2} className="field-textarea code-font" style={{ fontSize: 11 }}
              placeholder="SELECT * FROM customers WHERE status = 'active'"
              value={data.db_query ?? ''} disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { db_query: e.target.value })} />
            <span className="field-hint">If provided, this custom query will be used instead of reading whole tables.</span>
          </div>
          </>
        ) : isFileBased && inputMode === 'upload' ? (
          <div className="form-group">
            <div
              style={{
                border: isDragOver ? '2px dashed #2563eb' : '2px dashed #cbd5e1',
                borderRadius: 8,
                padding: '12px 14px',
                textAlign: 'center',
                cursor: 'pointer',
                background: isDragOver ? '#eff6ff' : data.source ? '#f0fdf4' : '#f8fafc',
                transition: 'all 0.15s ease',
              }}
              onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setIsDragOver(false)
                if (e.dataTransfer.files) handleFileUpload(e.dataTransfer.files)
              }}
              onClick={() => !uploading && fileInputRef.current?.click()}
            >
              <span style={{ fontSize: 22 }}>📁</span>
              <p style={{ margin: '4px 0 2px', fontSize: 12, fontWeight: 600, color: '#334155' }}>
                {uploading
                  ? 'Uploading & extracting files…'
                  : uploadedFiles.length > 0
                  ? `${uploadedFiles.length} file(s) attached`
                  : 'Click or drag & drop documents / ZIP'}
              </p>
              <span className="field-hint" style={{ fontSize: 11 }}>
                Single file, multiple files, or .zip archive (PDF, TXT, CSV, DOCX, MD, EML, images)
              </span>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.txt,.md,.json,.docx,.zip,.csv,.xlsx,.eml,.msg,.png,.jpg,.jpeg,.tif,.tiff"
                style={{ display: 'none' }}
                disabled={readOnly || uploading}
                onChange={(e) => handleFileUpload(e.target.files)}
              />
            </div>

            {uploadStatus && (
              <div style={{ marginTop: 6, fontSize: 11, color: uploadStatus.startsWith('✓') ? '#15803d' : '#b91c1c' }}>
                {uploadStatus}
              </div>
            )}

            {data.source && (
              <div style={{ marginTop: 6, fontSize: 11, color: '#475569', wordBreak: 'break-all' }}>
                <strong>Resolved Path:</strong> <code className="code-font" style={{ background: '#f1f5f9', padding: '1px 4px', borderRadius: 3 }}>{data.source}</code>
              </div>
            )}
          </div>
        ) : (
          <div className="form-group">
            <label className="field-label">{loaderDef?.sourceLabel ?? 'Source'}</label>
            <input type="text" className="field-input code-font"
              placeholder={loaderDef?.placeholder ?? ''}
              value={data.source}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { source: e.target.value })} />
            <span className="field-hint">{loaderDef?.desc ?? 'The path, URL, or connection string for this document source.'}</span>
          </div>
        )}
      </div>

      {OCR_LOADER_TYPES.has(data.loader_type) && (
        <div className="config-card">
          <h4 className="card-heading">Scanned pages (OCR)<HelpLink page="12-document-extraction" section="2-ocr-for-scanned-pages" label="Choosing an OCR engine" /></h4>
          <div className="form-group">
            <label className="field-label">OCR engine</label>
            <select className="field-select" value={data.ocr_engine ?? 'auto'} disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { ocr_engine: e.target.value })}>
              {OCR_ENGINES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <span className="field-hint">Used only for pages without a text layer (scans) and images.</span>
          </div>
          {data.ocr_engine === 'vision' ? (
            <>
              <div className="form-group">
                <label className="field-label">Vision provider</label>
                <input type="text" className="field-input code-font" placeholder="openai"
                  value={data.ocr_provider ?? ''} disabled={readOnly}
                  onChange={(e) => onUpdate(activeNode.id, { ocr_provider: e.target.value })} />
              </div>
              <div className="form-group">
                <label className="field-label">Vision model</label>
                <input type="text" className="field-input code-font" placeholder="gpt-4o-mini"
                  value={data.ocr_model ?? ''} disabled={readOnly}
                  onChange={(e) => onUpdate(activeNode.id, { ocr_model: e.target.value })} />
                <span className="field-hint">
                  Page images are sent to this provider, using the project's key from Settings. OpenAI-compatible,
                  Anthropic and Ollama models.
                </span>
              </div>
            </>
          ) : data.ocr_engine !== 'off' && (
            <div className="form-group">
              <label className="field-label">Language</label>
              <input type="text" className="field-input code-font" placeholder="eng"
                value={data.ocr_language ?? ''} disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { ocr_language: e.target.value })} />
              <span className="field-hint">Tesseract language codes, e.g. eng or eng+spa.</span>
            </div>
          )}
        </div>
      )}

      <div className="config-card">
        <h4 className="card-heading">3. Chunk Strategy</h4>
        <div className="form-group">
          <label className="field-label">Pre-chunking Strategy</label>
          <select className="field-select" value={data.chunk_strategy} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { chunk_strategy: e.target.value as DocLoaderNodeData['chunk_strategy'] })}>
            <option value="fixed">Fixed — Pass raw content to Text Splitter</option>
            <option value="paragraph">Paragraph — Split on double newlines before passing</option>
            <option value="sentence">Sentence — Sentence-boundary pre-split</option>
          </select>
          <span className="field-hint">This is applied at load time. Fine-grained splitting happens in the Text Splitter node.</span>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
        <div className="tool-status-box dl-status-box">
          <span className="status-dot dl-dot" />
          <span>RAG pipeline: Loader → Splitter → Embedding → Vector Store</span>
        </div>
        {!readOnly && (
          <div className="card-actions-row">
            <button type="button" className="save-btn" onClick={onSave}>Save to App</button>
            <button type="button" className="delete-btn" onClick={() => onDelete(activeNode.id)}>Delete Node</button>
          </div>
        )}
      </div>
    </div>
  )
}
