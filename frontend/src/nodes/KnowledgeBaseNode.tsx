import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { KnowledgeBaseNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

export function KnowledgeBaseNode({ data, selected }: NodeProps<Node<KnowledgeBaseNodeData, 'knowledge_base'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`tool-node-card kb-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="kb-target-left" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Left} id="kb-source-left" className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Top} id="kb-target-top" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Top} id="kb-source-top" className="flow-handle tool-handle" />

      <div className="node-card-header kb-node-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="knowledge_base" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button
          type="button"
          className="node-delete-btn"
          title="Remove knowledge base node"
          onClick={(e) => {
            e.stopPropagation()
            data.onDelete?.()
          }}
        >
          ✕
        </button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-kb">
            KNOWLEDGE BASE ({data.chunk_count || 0} CHUNKS)
          </span>
        </div>
        <p className="tool-node-desc">
          {data.description || `Semantic vector search index over ${data.chunk_count || 0} indexed passages.`}
        </p>
        <div className="kb-node-meta" style={{ fontSize: 10, color: '#4338ca', marginTop: 4 }}>
          🔍 Top-{data.top_k || 4} • {data.embedding_provider === 'openai' ? 'OpenAI' : 'Local MiniLM'}
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status">{isCardSelected ? '● Configured in Panel' : 'Connect to Agent / LLM'}</span>
      </div>

      <Handle type="target" position={Position.Right} id="kb-target-right" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Right} id="kb-source-right" className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Bottom} id="kb-target-bottom" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Bottom} id="kb-source-bottom" className="flow-handle tool-handle" />
    </div>
  )
}
