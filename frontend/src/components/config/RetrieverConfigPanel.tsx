import type { RetrieverNodeData, FlowNode } from '../../types'
import { ApiKeyField } from './ApiKeyField'

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

const OPENAI_EMBEDDING_MODELS = [
  'text-embedding-3-small',
  'text-embedding-3-large',
  'text-embedding-ada-002',
]

const LOCAL_EMBEDDING_MODELS = [
  'sentence-transformers/all-MiniLM-L6-v2',
  'sentence-transformers/all-mpnet-base-v2',
  'BAAI/bge-small-en-v1.5',
  'BAAI/bge-large-en-v1.5',
]

export function RetrieverConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as RetrieverNodeData
  const modelOptions = data.embedding_provider === 'openai' ? OPENAI_EMBEDDING_MODELS : LOCAL_EMBEDDING_MODELS

  return (
    <div className="bottom-config-grid">
      {/* Card 1 — Identity & Search Type */}
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Search Type</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input
            type="text"
            className="field-input"
            value={data.label}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label className="field-label">Search Type</label>
          <select
            className="field-select"
            value={data.search_type}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { search_type: e.target.value as RetrieverNodeData['search_type'] })}
          >
            <option value="similarity">Similarity Search — Standard cosine top-k</option>
            <option value="mmr">MMR (Max Marginal Relevance) — Diverse, less repetition</option>
            <option value="bm25_hybrid">BM25 Hybrid — Dense vector + sparse keyword retrieval</option>
          </select>
          <span className="field-hint">
            {data.search_type === 'similarity' && 'Returns the top-k chunks most similar to the query by cosine distance.'}
            {data.search_type === 'mmr' && 'Balances relevance with diversity — avoids returning near-duplicate chunks.'}
            {data.search_type === 'bm25_hybrid' && 'Combines semantic (vector) and keyword (BM25) scores for best recall.'}
          </span>
        </div>
      </div>

      {/* Card 2 — Collection & Retrieval Settings */}
      <div className="config-card">
        <h4 className="card-heading">2. Collection &amp; Retrieval</h4>
        <div className="form-group">
          <label className="field-label">Collection Name</label>
          <input
            type="text"
            className="field-input code-font"
            placeholder="my_documents"
            value={data.collection_name}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { collection_name: e.target.value })}
          />
          <span className="field-hint">Must match the collection used in your Vector Store node.</span>
        </div>
        <div className="form-group">
          <label className="field-label">Top-K Results</label>
          <input
            type="number"
            className="field-input"
            min="1"
            max="50"
            step="1"
            value={data.top_k}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { top_k: parseInt(e.target.value) || 5 })}
          />
          <span className="field-hint">Number of chunks returned per query. 3–8 is typical for RAG.</span>
        </div>
        <div className="form-group">
          <label className="field-label">Score Threshold</label>
          <input
            type="number"
            className="field-input"
            min="0"
            max="1"
            step="0.05"
            value={data.score_threshold}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { score_threshold: parseFloat(e.target.value) || 0 })}
          />
          <span className="field-hint">Chunks with similarity below this score are filtered out. 0 = no filter.</span>
        </div>
      </div>

      {/* Card 3 — Embedding (for query-time) */}
      <div className="config-card">
        <h4 className="card-heading">3. Query Embedding</h4>
        <div className="form-group">
          <label className="field-label">Embedding Provider</label>
          <select
            className="field-select"
            value={data.embedding_provider}
            disabled={readOnly}
            onChange={(e) => {
              const prov = e.target.value as RetrieverNodeData['embedding_provider']
              const defaultModel = prov === 'openai' ? OPENAI_EMBEDDING_MODELS[0] : LOCAL_EMBEDDING_MODELS[0]
              onUpdate(activeNode.id, { embedding_provider: prov, embedding_model: defaultModel })
            }}
          >
            <option value="openai">OpenAI — text-embedding-3-small / large</option>
            <option value="local">Local — sentence-transformers (HuggingFace)</option>
          </select>
          <span className="field-hint">Must match the provider used when ingesting documents.</span>
        </div>
        <div className="form-group">
          <label className="field-label">Embedding Model</label>
          <select
            className="field-select"
            value={data.embedding_model}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { embedding_model: e.target.value })}
          >
            {modelOptions.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
        {data.embedding_provider === 'openai' && (
          <div className="form-group">
            <label className="field-label">OpenAI API Key</label>
            <ApiKeyField provider={data.embedding_provider} value={data.embedding_api_key} readOnly={readOnly}
              placeholder="sk-..." onChange={(v) => onUpdate(activeNode.id, { embedding_api_key: v })} />
          </div>
        )}
      </div>

      {/* Card 4 — Rerank & Actions */}
      <div className="config-card">
        <h4 className="card-heading">4. Rerank &amp; Actions</h4>
        <div className="form-group">
          <label className="field-label">
            <input
              type="checkbox"
              checked={data.rerank}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { rerank: e.target.checked })}
              style={{ marginRight: 8 }}
            />
            Enable Reranking
          </label>
          <span className="field-hint">Re-scores top-k results using a cross-encoder for higher precision. Adds latency.</span>
        </div>
        <div className="tool-status-box ret-status-box">
          <span className="status-dot ret-dot" />
          <span>
            {data.search_type === 'similarity' && 'Cosine similarity search over stored embeddings'}
            {data.search_type === 'mmr' && 'MMR: diverse top-k using cosine + redundancy penalty'}
            {data.search_type === 'bm25_hybrid' && 'Hybrid: dense vector + BM25 keyword fusion'}
          </span>
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
