import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { StartNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

export function StartNode({ data, selected }: NodeProps<Node<StartNodeData, 'start'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`start-node-card ${isCardSelected ? 'selected' : ''}`}>
      <div className="node-card-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="start" /></span>
          <span className="node-title">{data.label || 'Start'}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <span className="chip chip-start">PIPELINE START</span>
      </div>

      <Handle type="source" position={Position.Right} id="start-source-right" className="flow-handle" />
      <Handle type="source" position={Position.Bottom} id="start-source-bottom" className="flow-handle" />
    </div>
  )
}
