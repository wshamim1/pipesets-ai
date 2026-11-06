import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { CheckpointerNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'


export function CheckpointerNode({ data, selected }: NodeProps<Node<CheckpointerNodeData, 'checkpointer'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`checkpointer-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left}   id="cp-target-left"   className="flow-handle cp-handle" />
      <Handle type="source" position={Position.Left}   id="cp-source-left"   className="flow-handle cp-handle" />
      <Handle type="target" position={Position.Top}    id="cp-target-top"    className="flow-handle cp-handle" />
      <Handle type="source" position={Position.Top}    id="cp-source-top"    className="flow-handle cp-handle" />

      <div className="node-card-header checkpointer-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="checkpointer" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-memory">CHECKPOINTER</span>
          <span className="chip model-chip">{data.save_steps ? 'app database' : 'status only'}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Save steps: <strong>{data.save_steps ? 'Yes' : 'No'}</strong></span>
          <span className="meta-item">On resume: <strong>{data.save_steps && data.restore_on_resume ? 'continue' : 'start over'}</strong></span>
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status cp-footer-status">
          {isCardSelected ? '● Active in Bottom Config' : 'Applies to the whole run'}
        </span>
      </div>

      <Handle type="target" position={Position.Right}  id="cp-target-right"  className="flow-handle cp-handle" />
      <Handle type="source" position={Position.Right}  id="cp-source-right"  className="flow-handle cp-handle" />
      <Handle type="target" position={Position.Bottom} id="cp-target-bottom" className="flow-handle cp-handle" />
      <Handle type="source" position={Position.Bottom} id="cp-source-bottom" className="flow-handle cp-handle" />
    </div>
  )
}
