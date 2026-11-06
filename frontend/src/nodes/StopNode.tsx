import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { StopNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

export function StopNode({ data, selected }: NodeProps<Node<StopNodeData, 'stop'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`stop-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="stop-target-left" className="flow-handle" />
      <Handle type="target" position={Position.Top} id="stop-target-top" className="flow-handle" />

      <div className="node-card-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="stop" /></span>
          <span className="node-title">{data.label || 'Stop'}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <span className="chip chip-stop">PIPELINE STOP</span>
      </div>
    </div>
  )
}
