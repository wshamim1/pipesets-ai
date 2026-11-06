import type { TextSplitterNodeData, FlowNode } from '../../types'

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

export function TextSplitterConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as TextSplitterNodeData

  return (
    <div className="bottom-config-grid">
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Splitter Type</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Splitter Type</label>
          <select className="field-select" value={data.splitter_type} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { splitter_type: e.target.value as TextSplitterNodeData['splitter_type'] })}>
            <option value="recursive_character">Recursive Character — Smart split on separators</option>
            <option value="token">Token-based — Split by token count (tiktoken)</option>
            <option value="markdown">Markdown-aware — Respect headers and code blocks</option>
          </select>
          <span className="field-hint">Recursive Character is the best general-purpose choice.</span>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">2. Chunk Size &amp; Overlap</h4>
        <div className="form-group">
          <label className="field-label">Chunk Size</label>
          <input type="number" className="field-input" min="64" max="8192" step="64" value={data.chunk_size}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { chunk_size: parseInt(e.target.value) || 512 })} />
          <span className="field-hint">
            {data.splitter_type === 'token'
              ? `${data.chunk_size} tokens per chunk (~${Math.round(data.chunk_size * 4)} characters)`
              : `${data.chunk_size} characters per chunk`}
          </span>
        </div>
        <div className="form-group">
          <label className="field-label">Chunk Overlap</label>
          <input type="number" className="field-input" min="0" max="2048" step="16" value={data.chunk_overlap}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { chunk_overlap: parseInt(e.target.value) || 50 })} />
          <span className="field-hint">Overlap keeps context across chunk boundaries. Typically 10–20% of chunk size.</span>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">3. Info</h4>
        <div className="tool-status-box ts-status-box">
          <span className="status-dot ts-dot" />
          <span>Splits document text into chunks for embedding</span>
        </div>
        <div className="ts-info-box">
          <p className="field-hint">Effective chunks: input ÷ (chunk_size − overlap). Lower overlap = fewer chunks, less context bleed. Higher overlap = more retrieval coverage but more tokens per query.</p>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
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
