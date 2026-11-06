import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { SyntheticDataNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

export function SyntheticDataNode({ data, selected }: NodeProps<Node<SyntheticDataNodeData, 'synthetic_data'>>) {
  const isCardSelected = selected || data.isSelected
  const columnCount = Array.isArray(data.columns) ? data.columns.length : 0

  return (
    <div className={`tool-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="syn-target-left" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Left} id="syn-source-left" className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Top} id="syn-target-top" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Top} id="syn-source-top" className="flow-handle tool-handle" />

      <div className="node-card-header tool-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="synthetic_data" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-tool">SYNTHETIC DATA</span>
          <span className="chip model-chip">{data.output_format.toUpperCase()}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Rows: <strong>{data.row_count}</strong></span>
          <span className="meta-item">Cols: <strong>{columnCount}</strong></span>
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status">{isCardSelected ? '● Configured in Panel' : (data.dataset_name || 'Set schema in config')}</span>
      </div>

      <Handle type="target" position={Position.Right} id="syn-target-right" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Right} id="syn-source-right" className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Bottom} id="syn-target-bottom" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Bottom} id="syn-source-bottom" className="flow-handle tool-handle" />
    </div>
  )
}
