import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { ConnectionNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

export function ConnectionNode({ data, selected }: NodeProps<Node<ConnectionNodeData, 'connection'>>) {
  const isCardSelected = selected || data.isSelected
  const isConnected = data.status === 'connected'

  return (
    <div className={`tool-node-card connection-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="conn-target-left" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Left} id="conn-source-left" className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Top} id="conn-target-top" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Top} id="conn-source-top" className="flow-handle tool-handle" />

      <div className="node-card-header connection-node-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="connection" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button
          type="button"
          className="node-delete-btn"
          title="Remove connection node"
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
          <span className={`chip ${isConnected ? 'chip-connected' : 'chip-untested'}`}>
            {isConnected ? 'LIVE CONNECTION' : `${data.connection_type.toUpperCase()} • ${data.status.toUpperCase()}`}
          </span>
        </div>
        <p className="tool-node-desc">
          {data.description || `${data.connection_type.toUpperCase()} Data Source`}
        </p>
        {data.status_msg && (
          <div className="connection-node-status-msg" style={{ fontSize: 10, color: isConnected ? '#15803d' : '#b91c1c' }}>
            {isConnected ? '🟢' : '🔴'} {data.status_msg.slice(0, 45)}
          </div>
        )}
      </div>

      <div className="node-card-footer">
        <span className="footer-status">{isCardSelected ? '● Configured in Panel' : 'Connect to Tool / RAG'}</span>
      </div>

      <Handle type="target" position={Position.Right} id="conn-target-right" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Right} id="conn-source-right" className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Bottom} id="conn-target-bottom" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Bottom} id="conn-source-bottom" className="flow-handle tool-handle" />
    </div>
  )
}
