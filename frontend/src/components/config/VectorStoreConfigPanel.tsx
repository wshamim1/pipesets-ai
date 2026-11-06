import type { VectorStoreNodeData, FlowNode } from '../../types'
import { LIVE_VECTOR_STORES } from '../../types'

const COMING_SOON: [VectorStoreNodeData['store_type'], string][] = [
  ['chroma', 'Chroma'], ['pinecone', 'Pinecone'], ['weaviate', 'Weaviate'], ['qdrant', 'Qdrant'],
  ['milvus', 'Milvus'], ['elasticsearch', 'Elasticsearch'], ['mongodb_atlas', 'MongoDB Atlas'],
  ['opensearch', 'AWS OpenSearch'], ['redis', 'Redis'], ['faiss', 'FAISS'],
  ['azure_ai_search', 'Azure AI Search'], ['vertex_ai', 'Vertex AI Vector Search'], ['lancedb', 'LanceDB'],
]

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

export function VectorStoreConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as VectorStoreNodeData

  return (
    <div className="bottom-config-grid">
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Store Type</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Vector Store Backend</label>
          <select className="field-select" value={data.store_type} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { store_type: e.target.value as VectorStoreNodeData['store_type'] })}>
            <option value="local">Local — built into the app database, zero setup</option>
            <option value="pgvector">pgvector — Postgres extension, HNSW index</option>
            <optgroup label="Coming soon">
              {COMING_SOON.map(([value, name]) => (
                <option key={value} value={value} disabled>{name}</option>
              ))}
            </optgroup>
          </select>
          {data.store_type === 'chroma' ? (
            <span className="field-hint">Chroma isn't connected yet — this node stores chunks in the Local store. Switch to Local to make that explicit.</span>
          ) : !LIVE_VECTOR_STORES.has(data.store_type) ? (
            <span className="field-hint vs-unsupported">This backend isn't available yet, so ingesting will fail. Switch to Local or pgvector.</span>
          ) : (
            <span className="field-hint">Local is easiest to start with. Use pgvector for larger collections or production.</span>
          )}
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">2. Collection &amp; Connection</h4>
        <div className="form-group">
          <label className="field-label">Collection / Index Name</label>
          <input type="text" className="field-input code-font"
            placeholder="my_documents"
            value={data.collection_name}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { collection_name: e.target.value })} />
          <span className="field-hint">A logical namespace for your embeddings. Use separate collections per document set.</span>
        </div>
        {data.store_type === 'pgvector' && (
          <div className="form-group">
            <label className="field-label">Postgres Connection String</label>
            <input type="text" className="field-input code-font"
              placeholder="postgresql://user:pass@localhost:5432/db"
              value={data.connection_string}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { connection_string: e.target.value })} />
            <span className="field-hint">
              Leave blank to use the server's <code>PGVECTOR_URL</code>. The database needs the pgvector
              extension (<code>CREATE EXTENSION vector</code>), or a role allowed to create it.
            </span>
          </div>
        )}
      </div>

      <div className="config-card">
        <h4 className="card-heading">3. Retrieval Settings</h4>
        <div className="form-group">
          <label className="field-label">Top-K Results</label>
          <input type="number" className="field-input" min="1" max="50" step="1" value={data.top_k}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { top_k: parseInt(e.target.value) || 5 })} />
          <span className="field-hint">How many similar chunks to return per query. 3–8 is typical for RAG.</span>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
        <div className="tool-status-box vs-status-box">
          <span className="status-dot vs-dot" />
          <span>Stores and retrieves dense vector embeddings</span>
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
