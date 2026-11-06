import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { MemoryNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

export function MemoryNode({ data, selected }: NodeProps<Node<MemoryNodeData, 'memory'>>) {
  const isCardSelected = selected || data.isSelected
  const strategyLabel = ({ sliding_window: 'Sliding Window', summarize: 'Summarize', last_k: 'Last K Turns', vector: 'Vector Store', knowledge_graph: 'Knowledge Graph' } as Record<string, string>)[data.strategy] ?? data.strategy

  return (
    <div className={`memory-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="mem-target-left" className="flow-handle mem-handle" />
      <Handle type="source" position={Position.Left} id="mem-source-left" className="flow-handle mem-handle" />
      <Handle type="target" position={Position.Top} id="mem-target-top" className="flow-handle mem-handle" />
      <Handle type="source" position={Position.Top} id="mem-source-top" className="flow-handle mem-handle" />

      <div className="node-card-header memory-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="memory" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-memory">MEMORY</span>
          <span className="chip model-chip">{strategyLabel}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Budget: <strong>{data.token_budget.toLocaleString()}</strong> tk</span>
          <span className="meta-item">TTL: <strong>{data.session_ttl_hours}h</strong></span>
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status mem-session-id">
          {isCardSelected ? '● Configured in Panel' : `Session: ${data.session_id || 'auto'}`}
        </span>
      </div>

      <Handle type="target" position={Position.Right} id="mem-target-right" className="flow-handle mem-handle" />
      <Handle type="source" position={Position.Right} id="mem-source-right" className="flow-handle mem-handle" />
      <Handle type="target" position={Position.Bottom} id="mem-target-bottom" className="flow-handle mem-handle" />
      <Handle type="source" position={Position.Bottom} id="mem-source-bottom" className="flow-handle mem-handle" />
    </div>
  )
}
