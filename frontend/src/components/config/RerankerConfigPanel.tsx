import type { RerankerNodeData, FlowNode } from '../../types'
import { ApiKeyField } from './ApiKeyField'

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

const COHERE_MODELS = ['rerank-english-v3.0', 'rerank-multilingual-v3.0', 'rerank-english-v2.0']
const CROSS_ENCODER_MODELS = ['cross-encoder/ms-marco-MiniLM-L-6-v2', 'cross-encoder/ms-marco-MiniLM-L-12-v2', 'cross-encoder/ms-marco-TinyBERT-L-2-v2']
const FLASHRANK_MODELS = ['ms-marco-MiniLM-L-12-v2', 'ms-marco-TinyBERT-L-2-v2', 'rank-T5-flan']
const BGE_MODELS = ['BAAI/bge-reranker-v2-m3', 'BAAI/bge-reranker-large', 'BAAI/bge-reranker-base']

function modelsFor(type: RerankerNodeData['reranker_type']) {
  if (type === 'cohere')        return COHERE_MODELS
  if (type === 'cross_encoder') return CROSS_ENCODER_MODELS
  if (type === 'flashrank')     return FLASHRANK_MODELS
  return BGE_MODELS
}

export function RerankerConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as RerankerNodeData
  const models = modelsFor(data.reranker_type)

  return (
    <div className="bottom-config-grid">
      {/* Card 1 — Identity & Type */}
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Type</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Reranker Type</label>
          <select className="field-select" value={data.reranker_type} disabled={readOnly}
            onChange={(e) => {
              const t = e.target.value as RerankerNodeData['reranker_type']
              onUpdate(activeNode.id, { reranker_type: t, model: modelsFor(t)[0] })
            }}>
            <option value="cohere">Cohere — Managed rerank API (state-of-the-art)</option>
            <option value="cross_encoder">CrossEncoder — HuggingFace, runs locally</option>
            <option value="flashrank">FlashRank — Ultra-fast local reranker</option>
            <option value="bge">BGE Reranker — Best open-source multilingual</option>
          </select>
        </div>
      </div>

      {/* Card 2 — Model & Top-N */}
      <div className="config-card">
        <h4 className="card-heading">2. Model &amp; Top-N</h4>
        <div className="form-group">
          <label className="field-label">Model</label>
          <select className="field-select" value={data.model} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { model: e.target.value })}>
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label className="field-label">Top-N (results to return)</label>
          <input type="number" className="field-input" min="1" max="50" step="1" value={data.top_n}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { top_n: parseInt(e.target.value) || 5 })} />
          <span className="field-hint">Re-ranks the retrieved chunks and returns the top N.</span>
        </div>
      </div>

      {/* Card 3 — API Key (Cohere only) & Actions */}
      <div className="config-card">
        <h4 className="card-heading">3. Credentials &amp; Actions</h4>
        {data.reranker_type === 'cohere' && (
          <div className="form-group">
            <label className="field-label">Cohere API Key</label>
            <ApiKeyField provider="cohere" value={data.api_key} readOnly={readOnly} placeholder="co-..."
              onChange={(v) => onUpdate(activeNode.id, { api_key: v })} />
          </div>
        )}
        {data.reranker_type !== 'cohere' && (
          <div className="tool-status-box ret-status-box">
            <span className="status-dot ret-dot" />
            <span>Runs locally — no API key required.</span>
          </div>
        )}
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
