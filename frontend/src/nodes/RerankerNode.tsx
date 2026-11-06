import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { RerankerNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'


export function RerankerNode({ data, selected }: NodeProps<Node<RerankerNodeData, 'reranker'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`reranker-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left}   id="rer-target-left"   className="flow-handle rer-handle" />
      <Handle type="source" position={Position.Left}   id="rer-source-left"   className="flow-handle rer-handle" />
      <Handle type="target" position={Position.Top}    id="rer-target-top"    className="flow-handle rer-handle" />
      <Handle type="source" position={Position.Top}    id="rer-source-top"    className="flow-handle rer-handle" />

      <div className="node-card-header reranker-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="reranker" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-reranker">RERANKER</span>
          <span className="chip model-chip">{data.reranker_type}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Top-n: <strong>{data.top_n}</strong></span>
          <span className="meta-item model-label" title={data.model}>{data.model}</span>
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status rer-footer-status">
          {isCardSelected ? '● Active in Bottom Config' : 'Retriever → Reranker → LLM'}
        </span>
      </div>

      <Handle type="target" position={Position.Right}  id="rer-target-right"  className="flow-handle rer-handle" />
      <Handle type="source" position={Position.Right}  id="rer-source-right"  className="flow-handle rer-handle" />
      <Handle type="target" position={Position.Bottom} id="rer-target-bottom" className="flow-handle rer-handle" />
      <Handle type="source" position={Position.Bottom} id="rer-source-bottom" className="flow-handle rer-handle" />
    </div>
  )
}
