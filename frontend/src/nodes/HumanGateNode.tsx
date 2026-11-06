import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { HumanGateNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'


export function HumanGateNode({ data, selected }: NodeProps<Node<HumanGateNodeData, 'human_gate'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`human-gate-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left}   id="hg-target-left"   className="flow-handle hg-handle" />
      <Handle type="source" position={Position.Left}   id="hg-source-left"   className="flow-handle hg-handle" />
      <Handle type="target" position={Position.Top}    id="hg-target-top"    className="flow-handle hg-handle" />
      <Handle type="source" position={Position.Top}    id="hg-source-top"    className="flow-handle hg-handle" />

      <div className="node-card-header human-gate-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="human_gate" variant={data.gate_type} /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-memory">HUMAN GATE</span>
          <span className="chip model-chip">{data.gate_type}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Timeout: <strong>{data.timeout_hours}h</strong></span>
          <span className="meta-item">On timeout: <strong>{data.on_timeout}</strong></span>
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status hg-footer-status">
          {isCardSelected ? '● Active in Bottom Config' : 'Awaits human action'}
        </span>
      </div>

      <Handle type="target" position={Position.Right}  id="hg-target-right"  className="flow-handle hg-handle" />
      <Handle type="source" position={Position.Right}  id="hg-source-right"  className="flow-handle hg-handle" />
      <Handle type="target" position={Position.Bottom} id="hg-target-bottom" className="flow-handle hg-handle" />
      <Handle type="source" position={Position.Bottom} id="hg-source-bottom" className="flow-handle hg-handle" />
    </div>
  )
}
