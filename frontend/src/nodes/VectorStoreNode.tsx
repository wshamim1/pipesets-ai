import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { VectorStoreNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

const STORE_LABELS: Record<string, string> = {
  local: 'Local (built-in)',
  chroma: 'Chroma (local)',
  pgvector: 'pgvector (Postgres)',
  pinecone: 'Pinecone (cloud)',
  weaviate: 'Weaviate (cloud/self)',
  qdrant: 'Qdrant (cloud/self)',
  milvus: 'Milvus (self-hosted)',
  elasticsearch: 'Elasticsearch (ES)',
  mongodb_atlas: 'MongoDB Atlas',
  opensearch: 'AWS OpenSearch',
  redis: 'Redis (RedisVL)',
  faiss: 'FAISS (local)',
  azure_ai_search: 'Azure AI Search',
  vertex_ai: 'Vertex AI Vector Search',
  lancedb: 'LanceDB (serverless)',
}

export function VectorStoreNode({ data, selected }: NodeProps<Node<VectorStoreNodeData, 'vector_store'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`vector-store-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="vs-target-left" className="flow-handle vs-handle" />
      <Handle type="source" position={Position.Left} id="vs-source-left" className="flow-handle vs-handle" />
      <Handle type="target" position={Position.Top} id="vs-target-top" className="flow-handle vs-handle" />
      <Handle type="source" position={Position.Top} id="vs-source-top" className="flow-handle vs-handle" />

      <div className="node-card-header vector-store-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="vector_store" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-vector-store">VECTOR</span>
          <span className="chip model-chip">{STORE_LABELS[data.store_type] ?? data.store_type}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Collection: <strong>{data.collection_name || 'default'}</strong></span>
          <span className="meta-item">Top-k: <strong>{data.top_k}</strong></span>
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status vs-footer-status">
          {isCardSelected ? '● Configured in Panel' : 'Connect Embedding → Vector Store → LLM'}
        </span>
      </div>

      <Handle type="target" position={Position.Right} id="vs-target-right" className="flow-handle vs-handle" />
      <Handle type="source" position={Position.Right} id="vs-source-right" className="flow-handle vs-handle" />
      <Handle type="target" position={Position.Bottom} id="vs-target-bottom" className="flow-handle vs-handle" />
      <Handle type="source" position={Position.Bottom} id="vs-source-bottom" className="flow-handle vs-handle" />
    </div>
  )
}
