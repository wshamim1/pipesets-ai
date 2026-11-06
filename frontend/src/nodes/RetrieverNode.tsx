import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { RetrieverNodeData } from '../types'
import { DebugBadges } from './DebugBadges'
import { NodeIcon } from '../components/NodeIcon'

const SEARCH_LABELS: Record<string, string> = {
  similarity: 'Similarity Search',
  mmr: 'MMR (Diverse)',
  bm25_hybrid: 'BM25 Hybrid',
}

export function RetrieverNode({ data, selected }: NodeProps<Node<RetrieverNodeData, 'retriever'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`retriever-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="ret-target-left" className="flow-handle ret-handle" />
      <Handle type="source" position={Position.Left} id="ret-source-left" className="flow-handle ret-handle" />
      <Handle type="target" position={Position.Top} id="ret-target-top" className="flow-handle ret-handle" />
      <Handle type="source" position={Position.Top} id="ret-source-top" className="flow-handle ret-handle" />

      <div className="node-card-header retriever-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="retriever" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <DebugBadges data={data} />
        <button
          type="button"
          className="node-delete-btn"
          title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}
        >✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-retriever">RETRIEVER</span>
          <span className="chip model-chip">{SEARCH_LABELS[data.search_type] ?? data.search_type}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Top-k: <strong>{data.top_k}</strong></span>
          <span className="meta-item">Score ≥ <strong>{data.score_threshold}</strong></span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item ret-collection-label" title={data.collection_name}>
            {data.collection_name || 'default'}
          </span>
          {data.rerank && <span className="chip ret-rerank-chip">RERANK</span>}
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status ret-footer-status">
          {isCardSelected ? '● Configured in Panel' : 'Connect Vector Store → Retriever → LLM'}
        </span>
      </div>

      <Handle type="target" position={Position.Right} id="ret-target-right" className="flow-handle ret-handle" />
      <Handle type="source" position={Position.Right} id="ret-source-right" className="flow-handle ret-handle" />
      <Handle type="target" position={Position.Bottom} id="ret-target-bottom" className="flow-handle ret-handle" />
      <Handle type="source" position={Position.Bottom} id="ret-source-bottom" className="flow-handle ret-handle" />
    </div>
  )
}
